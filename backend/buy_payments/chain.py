"""Independent on-chain verification of a USDC payment on Arc Testnet.

The browser only reports a transaction hash. Nothing here trusts it: every fact that makes a
payment valid is read back from the chain's own RPC.

Payment transaction shape (sent from MetaMask):
    to    = USDC ERC-20 interface (0x3600…0000, 6 decimals)
    input = transfer(recipient, amount) ++ 32-byte payment reference
The token ignores the trailing reference (verified on Arc Testnet with eth_call/estimateGas),
but it is part of the signed transaction, so the transaction is provably for this payment.
"""
import httpx
from eth_utils import keccak
from backend.config import settings

TRANSFER_SELECTOR = 'a9059cbb'
TRANSFER_TOPIC = '0x' + keccak(text='Transfer(address,address,uint256)').hex()
BALANCE_OF = '70a08231'


class RpcError(Exception):
    """The RPC could not answer (rate limit, network). Never treated as a verdict."""


async def rpc(method, params):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(settings.arc_rpc_url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RpcError(f'{method}: {type(exc).__name__}') from exc
    if 'error' in data: raise RpcError(f"{method}: {data['error'].get('message', 'error')}")
    return data['result']


def word(hex_address_or_int):
    if isinstance(hex_address_or_int, int): return format(hex_address_or_int, '064x')
    return hex_address_or_int.lower().removeprefix('0x').rjust(64, '0')


def payment_reference(payment_id):
    return '0x' + keccak(text='mivo-buy-payment:' + payment_id).hex()


def expected_input(recipient, amount, reference):
    return '0x' + TRANSFER_SELECTOR + word(recipient) + word(int(amount)) + reference.removeprefix('0x').lower()


async def head_block():
    return int(await rpc('eth_blockNumber', []), 16)


async def token_balance(token, owner):
    return int(await rpc('eth_call', [{'to': token, 'data': '0x' + BALANCE_OF + word(owner)}, 'latest']), 16)


async def verify(p, tx_hash, confirmations):
    """Check one transaction against payment `p`.

    Returns (state, detail):
      'paid'       every check passed and enough confirmations; detail = block number
      'confirming' mined and matching, waiting for confirmations
      'pending'    known to the node but not mined yet
      'not_found'  the node does not know the transaction
      'reverted'   mined but failed (no USDC moved)
      'mismatch'   the transaction is not this payment; detail says why
    Raises RpcError when the chain could not be read (caller retries later).
    """
    chain_id = int(await rpc('eth_chainId', []), 16)
    if chain_id != p.chain_id: return 'mismatch', f'RPC is on chain {chain_id}, payment expects {p.chain_id}'
    tx = await rpc('eth_getTransactionByHash', [tx_hash])
    if not tx: return 'not_found', None
    if (tx.get('hash') or '').lower() != tx_hash.lower(): return 'mismatch', 'RPC returned a different transaction hash'
    if tx.get('chainId') is not None and int(tx['chainId'], 16) != p.chain_id: return 'mismatch', 'transaction was signed for another chain'
    if (tx.get('to') or '').lower() != p.token_address.lower(): return 'mismatch', 'transaction is not sent to the USDC token contract'
    if (tx.get('from') or '').lower() != (p.payer_address or '').lower(): return 'mismatch', 'transaction sender is not the approving wallet'
    if (tx.get('input') or '').lower() != expected_input(p.recipient_address, p.token_amount, p.reference):
        return 'mismatch', 'transaction recipient, amount or payment reference does not match'
    if tx.get('blockNumber') is None: return 'pending', None
    receipt = await rpc('eth_getTransactionReceipt', [tx_hash])
    if not receipt: return 'pending', None
    if int(receipt['status'], 16) != 1: return 'reverted', None
    transfers = [log for log in receipt.get('logs', [])
                 if log['address'].lower() == p.token_address.lower() and log['topics'] and log['topics'][0].lower() == TRANSFER_TOPIC
                 and len(log['topics']) == 3 and log['topics'][1].lower() == '0x' + word(p.payer_address)
                 and log['topics'][2].lower() == '0x' + word(p.recipient_address) and int(log['data'], 16) == int(p.token_amount)]
    if len(transfers) != 1: return 'mismatch', 'receipt has no matching USDC Transfer event'
    block = int(receipt['blockNumber'], 16)
    if await head_block() - block + 1 < confirmations: return 'confirming', block
    return 'paid', block


async def find_payment_tx(p, to_block=None):
    """Recover a payment whose hash never reached the backend (e.g. the tab closed after signing):
    look for USDC Transfers payer -> recipient since the payment started, and match the reference."""
    if not p.payer_address or p.start_block is None: return None
    logs = await rpc('eth_getLogs', [{'address': p.token_address, 'fromBlock': hex(p.start_block), 'toBlock': hex(to_block) if to_block else 'latest',
                                      'topics': [TRANSFER_TOPIC, '0x' + word(p.payer_address), '0x' + word(p.recipient_address)]}])
    want = expected_input(p.recipient_address, p.token_amount, p.reference)
    for log in logs:
        if int(log['data'], 16) != int(p.token_amount): continue
        tx = await rpc('eth_getTransactionByHash', [log['transactionHash']])
        if tx and (tx.get('input') or '').lower() == want: return log['transactionHash']
    return None
