import asyncio
from types import SimpleNamespace
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from backend.services import payments
from test_core import database,client,register

def test_wallet_proof_and_replay(client):
    register(client)
    account=Account.create()
    r=client.post('/wallet/challenge',json={'address':account.address});assert r.status_code==200
    challenge=r.json();signature='0x'+account.sign_message(encode_defunct(text=challenge['message'])).signature.hex()
    proof={'challenge_id':challenge['id'],'signature':signature}
    assert client.post('/wallet/verify',json=proof).status_code==200
    assert client.get('/wallet').json()['address']==account.address
    assert client.post('/wallet/verify',json=proof).status_code==409

def test_wallet_wrong_signer(client):
    register(client)
    account=Account.create();other=Account.create()
    c=client.post('/wallet/challenge',json={'address':account.address}).json()
    signature='0x'+other.sign_message(encode_defunct(text=c['message'])).signature.hex()
    assert client.post('/wallet/verify',json={'challenge_id':c['id'],'signature':signature}).status_code==403

def receipt_case():
    i=SimpleNamespace(chain_id=5042002,contract_address='0x'+'11'*20,buyer_address='0x'+'22'*20,merchant_address='0x'+'33'*20,token_address='0x'+'44'*20,quote_hash='0x'+'55'*32,token_amount='1000000',nonce='7',expires=1000)
    tx='0x'+'66'*32
    log={'address':i.contract_address,'topics':[payments.SETTLED_TOPIC,i.quote_hash,'0x'+'00'*12+i.buyer_address[2:],'0x'+'00'*12+i.merchant_address[2:]],'data':'0x'+'00'*12+i.token_address[2:]+int(i.token_amount).to_bytes(32).hex()+int(i.nonce).to_bytes(32).hex()}
    r={'transactionHash':tx,'status':'0x1','to':i.contract_address,'from':i.buyer_address,'blockNumber':'0xa','blockHash':'0x'+'77'*32,'logs':[log]}
    return i,tx,r

def mock_rpc(monkeypatch,r,chain=5042002,head=12,block_hash=None):
    async def rpc(method,params):
        return {'eth_chainId':hex(chain),'eth_getTransactionReceipt':r,'eth_blockNumber':hex(head),'eth_getBlockByNumber':{'hash':block_hash or r['blockHash'],'timestamp':'0x64'}}[method]
    monkeypatch.setattr(payments,'rpc',rpc)

def test_verified_receipt(monkeypatch):
    i,tx,r=receipt_case();mock_rpc(monkeypatch,r)
    assert asyncio.run(payments.verified_receipt(i,tx))==r
@pytest.mark.parametrize('mutation',['amount','merchant','contract','reverted','quote','token','nonce','chain','confirmations','reorg'])
def test_bad_receipts_rejected(monkeypatch,mutation):
    i,tx,r=receipt_case();kwargs={}
    if mutation=='amount':i.token_amount='2000000'
    elif mutation=='merchant':i.merchant_address='0x'+'aa'*20
    elif mutation=='contract':r['logs'][0]['address']='0x'+'bb'*20
    elif mutation=='reverted':r['status']='0x0'
    elif mutation=='quote':i.quote_hash='0x'+'cc'*32
    elif mutation=='token':i.token_address='0x'+'dd'*20
    elif mutation=='nonce':i.nonce='8'
    elif mutation=='chain':kwargs['chain']=1
    elif mutation=='confirmations':kwargs['head']=10
    elif mutation=='reorg':kwargs['block_hash']='0x'+'ee'*32
    mock_rpc(monkeypatch,r,**kwargs)
    with pytest.raises(ValueError):asyncio.run(payments.verified_receipt(i,tx))

def test_checkout_reservation_and_reconciliation(client,monkeypatch):
    from sqlalchemy import select
    from backend.api import payments as endpoints
    from backend.models import Product,Offer,Negotiation,Quote,WalletConnection,CheckoutIntent,Order,Payment
    from backend.db import SessionLocal
    from backend.config import settings
    from test_core import make_offer
    buyer=register(client);oid,nid=make_offer(buyer)
    qid=client.post('/offers/'+oid+'/accept').json()['id']
    with SessionLocal() as db:
        offer=db.get(Offer,oid);p=db.get(Product,offer.product_id);pid=p.id;stock=p.inventory
        db.add(WalletConnection(user_id=buyer['id'],address='0x'+'22'*20))
        db.add(WalletConnection(user_id=p.merchant_id,address='0x'+'33'*20));db.commit()
    monkeypatch.setattr(settings,'payment_enabled',True)
    monkeypatch.setattr(settings,'settlement_contract','0x'+'11'*20)
    async def config():return 100000000000
    monkeypatch.setattr(endpoints,'verify_configuration',config)
    monkeypatch.setattr(endpoints,'sign_authorization',lambda data:'0x'+'aa'*65)
    response=client.post('/quotes/'+qid+'/intent');assert response.status_code==200
    intent=response.json()
    assert client.post('/quotes/'+qid+'/intent').json()==intent
    with SessionLocal() as db:assert db.get(Product,pid).inventory==stock-1
    async def verified(i,tx):return {'blockNumber':'0x10','blockHash':'0x'+'77'*32}
    monkeypatch.setattr(endpoints,'verified_receipt',verified)
    tx='0x'+'66'*32
    assert client.post('/intents/'+intent['id']+'/confirm',json={'transaction_hash':tx}).status_code==200
    assert client.post('/intents/'+intent['id']+'/confirm',json={'transaction_hash':tx}).status_code==200
    assert client.get('/orders').json()[0]['transaction_hash']==tx
    with SessionLocal() as db:
        assert len(list(db.scalars(select(Order))))==1
        assert len(list(db.scalars(select(Payment))))==1
        assert db.get(Quote,qid).status=='paid'

def test_wallet_challenge_cross_account(client):
    account=Account.create();register(client)
    c=client.post('/wallet/challenge',json={'address':account.address}).json()
    signature='0x'+account.sign_message(encode_defunct(text=c['message'])).signature.hex()
    client.post('/auth/logout');register(client,email='second@example.com')
    assert client.post('/wallet/verify',json={'challenge_id':c['id'],'signature':signature}).status_code==409
