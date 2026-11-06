"""Testnet-only authorization and RPC-backed settlement verification."""
import secrets
from pathlib import Path
import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address
from backend.config import settings

FIELDS=[{'name':name,'type':kind} for name,kind in [('quoteId','bytes32'),('buyer','address'),('merchant','address'),('amount','uint256'),('nonce','uint256'),('deadline','uint256')]]
SETTLED_TOPIC='0x'+keccak(text='Settled(bytes32,address,address,address,uint256,uint256)').hex()

def enabled():
    return settings.payment_enabled and settings.arc_chain_id in (31337,5042002) and bool(settings.settlement_contract)

def typed_authorization(quote_hash,buyer,merchant,amount,nonce,deadline):
    return {'domain':{'name':'MivoSettlement','version':'1','chainId':settings.arc_chain_id,'verifyingContract':to_checksum_address(settings.settlement_contract)},'primaryType':'Authorization','types':{'EIP712Domain':[{'name':'name','type':'string'},{'name':'version','type':'string'},{'name':'chainId','type':'uint256'},{'name':'verifyingContract','type':'address'}],'Authorization':FIELDS},'message':{'quoteId':quote_hash,'buyer':to_checksum_address(buyer),'merchant':to_checksum_address(merchant),'amount':amount,'nonce':nonce,'deadline':deadline}}

def sign_authorization(data):
    path=Path(settings.quote_signer_file)
    if path.stat().st_mode & 0o077: raise ValueError('Signer file permissions must be private')
    return '0x'+Account.sign_message(encode_typed_data(full_message=data),path.read_text().strip()).signature.hex()

async def rpc(method,params):
    async with httpx.AsyncClient(timeout=15) as client:
        response=await client.post(settings.arc_rpc_url,json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
        response.raise_for_status();data=response.json()
    if 'error' in data: raise ValueError('RPC request failed')
    return data['result']

async def verify_configuration():
    if not enabled(): raise ValueError('Payments are disabled')
    if int(await rpc('eth_chainId',[]),16)!=settings.arc_chain_id: raise ValueError('Wrong RPC network')
    if await rpc('eth_getCode',[settings.settlement_contract,'latest']) in ('0x','0x0'): raise ValueError('Settlement contract is missing')
    async def call(signature):
        return await rpc('eth_call',[{'to':settings.settlement_contract,'data':'0x'+keccak(text=signature)[:4].hex()},'latest'])
    token=await call('token()')
    if ('0x'+token[-40:]).lower()!=settings.settlement_token.lower():raise ValueError('Unexpected settlement token')
    signer='0x'+(await call('signer()'))[-40:]
    key=Path(settings.quote_signer_file).read_text().strip()
    if Account.from_key(key).address.lower()!=signer.lower():raise ValueError('Signer does not match contract')
    decimals=await rpc('eth_call',[{'to':settings.settlement_token,'data':'0x313ce567'},'latest'])
    if int(decimals,16)!=settings.settlement_decimals:raise ValueError('Token decimals mismatch')
    return int(await call('spendingCap()'),16)

async def verified_receipt(intent,transaction_hash):
    if int(await rpc('eth_chainId',[]),16)!=intent.chain_id:raise ValueError('Wrong network')
    receipt=await rpc('eth_getTransactionReceipt',[transaction_hash])
    if not receipt:raise ValueError('Transaction is pending or unknown')
    if receipt.get('transactionHash','').lower()!=transaction_hash.lower():raise ValueError('Transaction hash mismatch')
    if int(receipt['status'],16)!=1:raise ValueError('Transaction reverted')
    if receipt.get('to','').lower()!=intent.contract_address.lower() or receipt.get('from','').lower()!=intent.buyer_address.lower():raise ValueError('Transaction parties mismatch')
    block=int(receipt['blockNumber'],16);latest=int(await rpc('eth_blockNumber',[]),16)
    if latest-block+1<settings.confirmations:raise ValueError('Awaiting confirmations')
    canonical=await rpc('eth_getBlockByNumber',[receipt['blockNumber'],False])
    if not canonical or canonical['hash'].lower()!=receipt['blockHash'].lower():raise ValueError('Receipt is not canonical')
    if int(canonical['timestamp'],16)>=intent.expires:raise ValueError('Settlement occurred after expiry')
    for log in receipt.get('logs',[]):
        topics=log.get('topics',[])
        if log.get('removed') or log.get('address','').lower()!=intent.contract_address.lower() or len(topics)!=4 or topics[0].lower()!=SETTLED_TOPIC.lower():continue
        if topics[1].lower()!=intent.quote_hash.lower() or ('0x'+topics[2][-40:]).lower()!=intent.buyer_address.lower() or ('0x'+topics[3][-40:]).lower()!=intent.merchant_address.lower():continue
        data=bytes.fromhex(log['data'].removeprefix('0x'))
        if len(data)!=96:continue
        token='0x'+data[12:32].hex();amount=int.from_bytes(data[32:64]);nonce=int.from_bytes(data[64:96])
        if token.lower()==intent.token_address.lower() and amount==int(intent.token_amount) and nonce==int(intent.nonce):return receipt
    raise ValueError('No matching settlement event')
