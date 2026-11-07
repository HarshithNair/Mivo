"""Device BUY -> MetaMask USDC payment -> on-chain verification (fake RPC; live checks in scripts/)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.api.main import app
from backend.config import settings
from backend.db import SessionLocal
from backend.models import Negotiation, Offer, Product, User, Quote, now
from backend.buy_payments import chain
from backend.buy_payments.config import payment_settings as ps
from backend.buy_payments.models import BuyPayment
from test_core import database

KEY = 'device-key'
BUYER = 'pi-owner@example.com'
RECIPIENT = '0x1111111111111111111111111111111111111111'
PAYER = '0x2222222222222222222222222222222222222222'
TOKEN = ps.payment_token_address
ORIGIN = {'origin': 'http://localhost:3000'}


class FakeChain:
    """Minimal Arc RPC: balances, one block head, and transactions we place on it."""
    def __init__(self):
        self.chain_id, self.head, self.balances, self.txs, self.receipts, self.logs = 5042002, 1000, {}, {}, {}, []
        self.calls = []

    def place(self, p, tx_hash, sender=PAYER, recipient=None, amount=None, reference=None, mined=True, status=1, token=TOKEN,
              chain_id=None, emit=True, block=None):
        recipient, amount, reference = recipient or p.recipient_address, int(amount or p.token_amount), reference or p.reference
        block = block or self.head
        self.txs[tx_hash] = {'hash': tx_hash, 'from': sender.lower(), 'to': token.lower(), 'chainId': hex(chain_id or self.chain_id),
                             'input': chain.expected_input(recipient, amount, reference), 'blockNumber': hex(block) if mined else None}
        log = {'address': token.lower(), 'transactionHash': tx_hash, 'data': hex(amount),
               'topics': [chain.TRANSFER_TOPIC, '0x' + chain.word(sender), '0x' + chain.word(recipient)]}
        if mined: self.receipts[tx_hash] = {'status': hex(status), 'blockNumber': hex(block), 'logs': [log] if emit and status == 1 else []}
        if mined and emit and status == 1: self.logs.append(log)

    async def rpc(self, method, params):
        self.calls.append(method)
        if method == 'eth_chainId': return hex(self.chain_id)
        if method == 'eth_blockNumber': return hex(self.head)
        if method == 'eth_call': return hex(self.balances.get(params[0]['data'][-40:].lower(), 0))
        if method == 'eth_getTransactionByHash': return self.txs.get(params[0])
        if method == 'eth_getTransactionReceipt': return self.receipts.get(params[0])
        if method == 'eth_getLogs':
            f = params[0]
            return [l for l in self.logs if l['topics'][1] == f['topics'][1] and l['topics'][2] == f['topics'][2]]
        raise AssertionError(method)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings, 'device_api_key', KEY)
    monkeypatch.setattr(settings, 'device_buyer_email', BUYER)
    monkeypatch.setattr(ps, 'payment_recipient_address', RECIPIENT)
    monkeypatch.setattr(ps, 'payment_check_interval', 0)
    monkeypatch.setattr(ps, 'payment_recovery_interval', 0)
    fake = FakeChain()
    monkeypatch.setattr(chain, 'rpc', fake.rpc)
    with TestClient(app) as c:
        r = c.post('/auth/register', headers=ORIGIN, json={'email': BUYER, 'name': 'Pi owner', 'password': 'correct-horse-battery', 'role': 'buyer'})
        assert r.status_code == 201
        c.chain = fake
        yield c


def deal(prices=(70000, 72500), expires_in=600, status='completed'):
    with SessionLocal() as db:
        buyer = db.scalar(select(User).where(User.email == BUYER))
        products = list(db.scalars(select(Product).where(Product.name == 'Studio ANC Headphones')))[:len(prices)]
        n = Negotiation(buyer_id=buyer.id, product_id=products[0].id, budget_cents=prices[0], status=status)
        db.add(n); db.flush()
        for product, price in zip(products, prices):
            product.floor_cents = min(product.floor_cents, price)
            db.add(Offer(negotiation_id=n.id, product_id=product.id, amount_cents=price, expires=now() + expires_in))
        db.commit()
        best = min(zip(prices, products))[1]
        return n.id, db.get(User, best.merchant_id).name


def buy(c, nid, request_id='req-00000001', **extra):
    return c.post('/device/buy', headers={'authorization': f'Bearer {KEY}'}, json={'command': 'buy', 'request_id': request_id, 'negotiation_id': nid, **extra})


def status(c, pid): return c.get(f'/device/payments/{pid}', headers={'authorization': f'Bearer {KEY}'}).json()


def payment(pid):
    with SessionLocal() as db: return db.get(BuyPayment, pid)


def approve(c, pid, payer=PAYER, balance=10 ** 12):
    c.chain.balances[payer[2:].lower()] = balance
    return c.post(f'/buy-payments/{pid}/start', headers=ORIGIN, json={'payer_address': payer})


TX = '0x' + 'ab' * 32


# ---- BUY signal ------------------------------------------------------------------------------

def test_buy_creates_pending_payment_from_best_offer(env):
    nid, dealer = deal()
    r = buy(env, nid, price_usd=700.00, dealer=dealer)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['status'] == 'pending' and body['payment_id'].startswith('PAY_') and body['amount'] == '700.00'
    p = payment(body['payment_id'])
    assert p.amount_cents == 70000 and p.token_amount == str(70000 * 10 ** 4)  # 700.00 USDC in 6-decimal units
    assert p.recipient_address.lower() == RECIPIENT and p.token_address == TOKEN and p.chain_id == 5042002
    assert p.reference == chain.payment_reference(p.id)
    with SessionLocal() as db:
        assert db.get(Negotiation, nid).status == 'accepted' and db.get(Quote, p.quote_id).amount_cents == 70000
    events = env.get('/buy-payments', headers=ORIGIN).json()[0]['events']
    assert [e['label'] for e in events] == ['BUY signal received', 'Payment pending']


def test_duplicate_buy_signals_never_create_a_second_payment(env):
    nid, _ = deal()
    first = buy(env, nid).json()['payment_id']
    assert buy(env, nid).json()['payment_id'] == first                         # same request_id (retransmit)
    assert buy(env, nid, request_id='req-00000002').json()['payment_id'] == first  # new press, same order
    with SessionLocal() as db: assert db.scalar(select(BuyPayment).where(BuyPayment.negotiation_id == nid).order_by(BuyPayment.attempt.desc())).attempt == 1


def test_buy_rejects_mismatched_or_invalid_requests(env):
    nid, dealer = deal()
    assert buy(env, nid, price_usd=650.00).status_code == 409
    assert buy(env, nid, dealer='Someone Else · Demo').status_code == 409
    assert buy(env, 'missing').status_code == 404
    assert env.post('/device/buy', headers={'authorization': 'Bearer wrong'}, json={'request_id': 'req-00000009', 'negotiation_id': nid}).status_code == 401
    assert env.post('/device/buy', headers={'authorization': f'Bearer {KEY}'}, json={'request_id': 'x', 'negotiation_id': nid}).status_code == 422
    expired, _ = deal(expires_in=-1)
    assert buy(env, expired, request_id='req-00000003').status_code == 410


def test_buy_requires_recipient(env, monkeypatch):
    monkeypatch.setattr(ps, 'payment_recipient_address', '')
    nid, _ = deal()
    assert buy(env, nid).status_code == 503


def test_one_payment_in_progress_per_buyer(env):
    a, _ = deal(); b, _ = deal()
    assert buy(env, a).status_code == 200
    assert buy(env, b, request_id='req-00000002').status_code == 429


# ---- MetaMask approval + on-chain verification -------------------------------------------------

def test_happy_path_paid_only_after_on_chain_verification(env):
    nid, _ = deal()
    pid = buy(env, nid).json()['payment_id']
    assert approve(env, pid).json()['status'] == 'awaiting_approval'
    p = payment(pid)
    # MetaMask returned a hash but the chain doesn't have it yet: must NOT be paid.
    assert env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX}).json()['status'] == 'submitted'
    assert status(env, pid)['status'] == 'submitted'
    env.chain.place(p, TX, mined=False)
    assert status(env, pid)['status'] == 'submitted'
    env.chain.place(p, TX)
    s = status(env, pid)
    assert s['status'] == 'paid' and s['tx_hash'] == TX and s['explorer_url'] == f'https://explorer.testnet.arc.io/tx/{TX}'
    assert s['amount'] == '700.00' and s['currency'] == 'USDC' and s['network'] == 'Arc Testnet'
    with SessionLocal() as db: assert db.get(Quote, payment(pid).quote_id).status == 'paid'
    # Bought means bought: no second payment for the same order.
    assert buy(env, nid, request_id='req-00000005').status_code == 409


def test_waits_for_confirmations(env, monkeypatch):
    monkeypatch.setattr(ps, 'payment_confirmations', 3)
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid); p = payment(pid)
    env.chain.place(p, TX, block=env.chain.head)
    env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX})
    assert status(env, pid)['status'] == 'confirming'
    env.chain.head += 2
    assert status(env, pid)['status'] == 'paid'


@pytest.mark.parametrize('tamper,reason', [
    (dict(recipient='0x3333333333333333333333333333333333333333'), 'recipient, amount or payment reference'),
    (dict(amount=1), 'recipient, amount or payment reference'),
    (dict(reference='0x' + 'cd' * 32), 'recipient, amount or payment reference'),
    (dict(sender='0x4444444444444444444444444444444444444444'), 'sender'),
    (dict(token='0x5555555555555555555555555555555555555555'), 'token contract'),
    (dict(chain_id=1), 'another chain'),
    (dict(emit=False), 'Transfer event'),
])
def test_rejects_transactions_that_are_not_this_payment(env, tamper, reason):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    env.chain.place(payment(pid), TX, **tamper)
    env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX})
    s = status(env, pid)
    assert s['status'] == 'failed' and reason in s['reason']


def test_wrong_rpc_chain_is_never_paid(env):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    env.chain.place(payment(pid), TX); env.chain.chain_id = 1
    env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX})
    assert status(env, pid)['status'] == 'failed'


def test_reverted_transaction_fails_and_allows_a_new_buy(env):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    env.chain.place(payment(pid), TX, status=0)
    env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX})
    assert status(env, pid)['status'] == 'failed'
    again = buy(env, nid, request_id='req-00000002').json()
    assert again['status'] == 'pending' and again['payment_id'] != pid


def test_unseen_transaction_times_out(env, monkeypatch):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX})
    monkeypatch.setattr(ps, 'payment_tx_timeout', -1)
    assert status(env, pid)['status'] == 'failed'
    # A sent-but-unconfirmed transaction blocks new attempts (it might still land).
    assert buy(env, nid, request_id='req-00000002').status_code == 409


def test_transaction_hash_cannot_pay_two_orders(env):
    a, _ = deal(); pa = buy(env, a).json()['payment_id']; approve(env, pa)
    env.chain.place(payment(pa), TX)
    env.post(f'/buy-payments/{pa}/submit', headers=ORIGIN, json={'tx_hash': TX})
    assert status(env, pa)['status'] == 'paid'
    b, _ = deal(); pb = buy(env, b, request_id='req-00000002').json()['payment_id']; approve(env, pb)
    assert env.post(f'/buy-payments/{pb}/submit', headers=ORIGIN, json={'tx_hash': TX}).status_code == 409
    assert env.post(f'/buy-payments/{pa}/submit', headers=ORIGIN, json={'tx_hash': '0x' + 'ef' * 32}).status_code == 409


def test_recovers_payment_when_hash_never_reached_backend(env):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    env.chain.place(payment(pid), TX)  # signed and mined, but the browser closed before reporting
    assert status(env, pid)['status'] == 'paid' and status(env, pid)['tx_hash'] == TX


# ---- failure handling ------------------------------------------------------------------------

def test_insufficient_balance_is_checked_on_chain(env):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']
    r = approve(env, pid, balance=5 * 10 ** 6)  # 5 USDC for a 700 USDC deal
    assert r.status_code == 409 and 'Insufficient USDC balance' in r.json()['detail']
    s = status(env, pid)
    assert s['status'] == 'failed' and '5.000000' in s['reason'] and '700.000000' in s['reason']


def test_wallet_rejection(env):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    assert env.post(f'/buy-payments/{pid}/report', headers=ORIGIN, json={'kind': 'rejected'}).json()['status'] == 'rejected'
    assert status(env, pid)['status'] == 'rejected'
    assert buy(env, nid, request_id='req-00000002').json()['status'] == 'pending'  # double-press again to retry


def test_cannot_pay_from_recipient_wallet(env):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']
    assert approve(env, pid, payer=RECIPIENT).status_code == 409


def test_approval_window_expires(env, monkeypatch):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']
    with SessionLocal() as db: db.get(BuyPayment, pid).expires = now() - 1; db.commit()
    assert status(env, pid)['status'] == 'expired'


def test_rpc_outage_never_changes_verdict(env, monkeypatch):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX})
    async def down(method, params): raise chain.RpcError('rate limit')
    monkeypatch.setattr(chain, 'rpc', down)
    assert status(env, pid)['status'] == 'submitted'


def test_payments_are_private(env):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']
    env.post('/auth/logout', headers=ORIGIN)
    env.post('/auth/register', headers=ORIGIN, json={'email': 'other@example.com', 'name': 'Other', 'password': 'correct-horse-battery', 'role': 'buyer'})
    assert env.get(f'/buy-payments/{pid}', headers=ORIGIN).status_code == 404
    assert env.post(f'/buy-payments/{pid}/start', headers=ORIGIN, json={'payer_address': PAYER}).status_code == 404
    # Website endpoints keep the browser Origin check.
    assert env.post(f'/buy-payments/{pid}/start', headers={'origin': 'https://evil.example'}, json={'payer_address': PAYER}).status_code == 403


def test_amount_units_use_erc20_decimals_not_native_gas_decimals():
    from backend.buy_payments.service import token_units
    assert token_units(69358) == 693_580_000  # 693.58 USDC at 6 decimals (NOT 18)


def test_arc_dual_transfer_events(env):
    """Arc emits two Transfer events per USDC transfer: a system one (0x…fffe) in 18-decimal native units and
    the token's own in 6-decimal units (seen on real Arc Testnet receipts). Only the token's event may count."""
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid); p = payment(pid)
    env.chain.place(p, TX)
    native = {'address': '0xfffffffffffffffffffffffffffffffffffffffe', 'transactionHash': TX, 'data': hex(int(p.token_amount) * 10 ** 12),
              'topics': [chain.TRANSFER_TOPIC, '0x' + chain.word(PAYER), '0x' + chain.word(p.recipient_address)]}
    env.chain.receipts[TX]['logs'].insert(0, native)
    env.post(f'/buy-payments/{pid}/submit', headers=ORIGIN, json={'tx_hash': TX})
    assert status(env, pid)['status'] == 'paid'


def test_balance_check_retries_once_on_busy_rpc(env, monkeypatch):
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']
    env.chain.balances[PAYER[2:].lower()] = 10 ** 12
    real, fails = env.chain.rpc, {'n': 0}
    async def flaky(method, params):
        if method == 'eth_call' and fails['n'] == 0: fails['n'] += 1; raise chain.RpcError('rate limit exceeded')
        return await real(method, params)
    monkeypatch.setattr(chain, 'rpc', flaky)
    import backend.buy_payments.service as svc
    async def no_sleep(*_): pass
    monkeypatch.setattr(svc.asyncio, 'sleep', no_sleep)
    assert env.post(f'/buy-payments/{pid}/start', headers=ORIGIN, json={'payer_address': PAYER}).json()['status'] == 'awaiting_approval'



def test_waiting_payments_do_not_hammer_the_rpc(env, monkeypatch):
    monkeypatch.setattr(ps, 'payment_recovery_interval', 20)
    nid, _ = deal(); pid = buy(env, nid).json()['payment_id']; approve(env, pid)
    env.chain.calls.clear()
    for _ in range(6): status(env, pid)  # Pi + portal polling while the user looks at MetaMask
    assert env.chain.calls.count('eth_getLogs') <= 1
