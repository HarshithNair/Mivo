"""Payment lifecycle: BUY -> pending -> awaiting_approval -> submitted -> confirming -> paid.

Only `refresh()` can set PAID, and only after chain.verify() checked the transaction on-chain.
"""
import json
import logging
from eth_utils import is_address, to_checksum_address
from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from backend.config import settings
from backend.models import Negotiation, Offer, Product, Quote, User, Audit, now
from backend.buy_payments import chain
from backend.buy_payments.config import payment_settings as ps
from backend.buy_payments.models import (BuyPayment, PENDING, AWAITING, SUBMITTED, CONFIRMING, PAID, FAILED,
                                         EXPIRED, REJECTED, ACTIVE)

log = logging.getLogger('mivo.buy_payments')
REVERTED = 'Transaction reverted on-chain; no USDC moved'

LABELS = {PENDING: 'Payment pending', AWAITING: 'Waiting for MetaMask approval', SUBMITTED: 'Transaction submitted',
          CONFIRMING: 'Transaction confirming', PAID: 'Payment successful', FAILED: 'Payment failed',
          EXPIRED: 'Payment failed', REJECTED: 'Payment failed'}


def recipient():
    address = ps.payment_recipient_address.strip()
    if not is_address(address) or int(address, 16) == 0:
        raise HTTPException(503, 'PAYMENT_RECIPIENT_ADDRESS is not set to a valid wallet address')
    return to_checksum_address(address)


def token_units(cents):
    if ps.payment_token_decimals < 2: raise HTTPException(503, 'Unsupported token decimals')
    return cents * 10 ** (ps.payment_token_decimals - 2)


def event(p, status, note=None):
    events = json.loads(p.events or '[]')
    events.append({'status': status, 'label': 'BUY signal received' if status == 'received' else LABELS.get(status, status), 'at': now(), 'note': note})
    p.events = json.dumps(events)


def set_status(p, status, reason=None, note=None):
    p.status = status
    if reason is not None: p.reason = reason
    event(p, status, note or reason)


# ---- BUY -------------------------------------------------------------------------------------

def create_from_buy(db, buyer, body):
    """Handle a device BUY. Idempotent per request_id; never more than one live payment per order."""
    to = recipient()
    same = db.scalar(select(BuyPayment).where(BuyPayment.request_id == body.request_id))
    if same:
        if same.buyer_id != buyer.id or same.negotiation_id != body.negotiation_id: raise HTTPException(409, 'request_id already used for another order')
        return same  # repeated press / retransmission: same payment, nothing new created
    n = db.get(Negotiation, body.negotiation_id)
    if not n or n.buyer_id != buyer.id: raise HTTPException(404, 'Negotiation not found')
    attempts = list(db.scalars(select(BuyPayment).where(BuyPayment.negotiation_id == n.id).order_by(BuyPayment.attempt)))
    if any(a.status == PAID for a in attempts): raise HTTPException(409, 'This deal is already bought and paid')
    live = [a for a in attempts if a.status in ACTIVE]
    if live: return live[0]  # duplicate BUY for an order already being paid: same payment
    # A sent transaction blocks new attempts unless the chain proved it moved nothing.
    if any(a.tx_hash and a.reason != REVERTED for a in attempts):
        raise HTTPException(409, 'A transaction was already sent for this deal; check Payments on the website')
    busy = db.scalar(select(func.count()).select_from(BuyPayment).where(BuyPayment.buyer_id == buyer.id, BuyPayment.status.in_(ACTIVE)))
    if busy: raise HTTPException(429, 'Another payment is still in progress; finish it on the website first')

    offer, quote = lock_offer(db, n, buyer)
    product = db.get(Product, offer.product_id)
    dealer = db.get(User, product.merchant_id).name
    if body.price_usd is not None and abs(round(body.price_usd * 100) - offer.amount_cents) > 0:
        raise HTTPException(409, f'Price changed: the deal is ${offer.amount_cents / 100:,.2f}, not ${body.price_usd:,.2f}')
    if body.dealer and body.dealer.strip() != dealer: raise HTTPException(409, f'Dealer changed: the deal is with {dealer}')
    p = BuyPayment(request_id=body.request_id, negotiation_id=n.id, attempt=(attempts[-1].attempt + 1) if attempts else 1,
                   offer_id=offer.id, quote_id=quote.id, buyer_id=buyer.id, product_name=product.name, dealer=dealer,
                   amount_cents=offer.amount_cents, token_amount=str(token_units(offer.amount_cents)),
                   token_address=to_checksum_address(ps.payment_token_address), recipient_address=to,
                   chain_id=settings.arc_chain_id, reference='0x' + '0' * 64, expires=now() + ps.payment_window)
    db.add(p); db.flush()
    p.reference = chain.payment_reference(p.id)
    event(p, 'received', f'{p.product_name} from {dealer} for {p.amount_cents / 100:,.2f} USDC')
    set_status(p, PENDING, note='Open Payments on the website and approve in MetaMask')
    db.add(Audit(actor=buyer.id, action='buy_payment_created', reference=p.id))
    try: db.commit()
    except IntegrityError:
        # Two BUYs raced: whichever won owns the order; return it.
        db.rollback()
        winner = db.scalar(select(BuyPayment).where(BuyPayment.request_id == body.request_id)) or \
            db.scalar(select(BuyPayment).where(BuyPayment.negotiation_id == n.id, BuyPayment.status.in_(ACTIVE)))
        if not winner: raise HTTPException(409, 'Payment could not be created; try again')
        return winner
    return p


def lock_offer(db, n, buyer):
    """Accept the negotiation's best (lowest) offer, mirroring the website's accept rules, or reuse
    the quote already accepted for it. The quote's validity is the payment window."""
    existing = db.scalar(select(Quote).where(Quote.negotiation_id == n.id))
    if existing:
        if existing.status == 'paid': raise HTTPException(409, 'This deal is already paid')
        if existing.expires <= now(): raise HTTPException(410, 'The accepted deal has expired; negotiate again')
        return db.get(Offer, existing.offer_id), existing
    if n.status != 'completed': raise HTTPException(409, f'Negotiation is {n.status}, not ready to buy')
    offer = db.scalar(select(Offer).where(Offer.negotiation_id == n.id).order_by(Offer.amount_cents).limit(1))
    if not offer: raise HTTPException(409, 'This negotiation has no offers')
    product = db.get(Product, offer.product_id)
    if offer.expires <= now(): raise HTTPException(410, 'The offer has expired; negotiate again')
    if product.inventory < 1 or offer.amount_cents < product.floor_cents: raise HTTPException(409, 'Offer is no longer valid')
    claimed = db.execute(update(Negotiation).where(Negotiation.id == n.id, Negotiation.status == 'completed').values(status='accepted'))
    if claimed.rowcount != 1: db.rollback(); raise HTTPException(409, 'Offer already accepted')
    quote = Quote(negotiation_id=n.id, offer_id=offer.id, buyer_id=buyer.id, amount_cents=offer.amount_cents, expires=now() + ps.payment_window)
    db.add(quote); db.add(Audit(actor=buyer.id, action='accept', reference=offer.id)); db.flush()
    return offer, quote


# ---- website actions --------------------------------------------------------------------------

def owned(db, pid, user):
    p = db.get(BuyPayment, pid)
    if not p or p.buyer_id != user.id: raise HTTPException(404, 'Payment not found')
    return p


async def start(db, p, payer):
    """The buyer clicked Pay: record the approving wallet and check its balance on-chain."""
    if p.status not in (PENDING, AWAITING): raise HTTPException(409, f'Payment is {LABELS.get(p.status, p.status).lower()}')
    if p.expires <= now(): set_status(p, EXPIRED, 'Not approved within the payment window'); db.commit(); raise HTTPException(410, p.reason)
    payer = to_checksum_address(payer)
    if payer.lower() == p.recipient_address.lower(): raise HTTPException(409, 'Pay from your buyer wallet, not the merchant (recipient) wallet')
    try:
        balance = await chain.token_balance(p.token_address, payer)
        head = await chain.head_block()
    except chain.RpcError: raise HTTPException(503, 'Arc Testnet RPC is busy; try again in a few seconds')
    if balance < int(p.token_amount):
        set_status(p, FAILED, f'Insufficient USDC balance: wallet has {balance / 10 ** ps.payment_token_decimals:,.6f}, '
                              f'needs {int(p.token_amount) / 10 ** ps.payment_token_decimals:,.6f}')
        p.payer_address = payer; db.commit()
        raise HTTPException(409, p.reason)
    p.payer_address, p.start_block = payer, max(head - 2, 0)
    if p.status != AWAITING: set_status(p, AWAITING, note=f'Wallet {payer}')
    db.commit()
    return p


async def submit(db, p, tx_hash):
    """MetaMask returned a hash. This is NOT success; it only tells the backend what to verify."""
    tx_hash = tx_hash.lower()
    if p.tx_hash:
        if p.tx_hash == tx_hash: return p
        raise HTTPException(409, 'A different transaction was already submitted for this payment')
    if p.status != AWAITING: raise HTTPException(409, f'Payment is {LABELS.get(p.status, p.status).lower()}')
    p.tx_hash, p.submitted_at = tx_hash, now()
    set_status(p, SUBMITTED, note=tx_hash)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409, 'That transaction is already used by another payment')
    return await refresh(db, p, force=True)


def report(db, p, kind, detail=None):
    """Browser-side outcomes that happen before any transaction exists."""
    if p.tx_hash or p.status not in (PENDING, AWAITING): return p
    if kind == 'rejected': set_status(p, REJECTED, 'Payment was rejected in MetaMask')
    elif kind == 'insufficient_gas': set_status(p, FAILED, 'Not enough native USDC for gas' + (f': {detail}' if detail else ''))
    else: raise HTTPException(422, 'Unknown report')
    db.commit()
    return p


# ---- verification -----------------------------------------------------------------------------

async def refresh(db, p, force=False):
    """Advance a payment using the chain as the source of truth. Safe to call on every poll."""
    if p.status not in ACTIVE: return p
    t = now()
    if not force and t - (p.last_checked or 0) < ps.payment_check_interval: return p
    p.last_checked = t
    try:
        if p.status in (PENDING, AWAITING):
            # Recover a transaction whose hash never reached us before deciding anything else.
            found = await chain.find_payment_tx(p) if p.status == AWAITING else None
            if found:
                p.tx_hash, p.submitted_at = found.lower(), t
                set_status(p, SUBMITTED, note='Recovered from chain: ' + found.lower())
            elif p.expires <= t:
                set_status(p, EXPIRED, 'Not approved in MetaMask within the payment window')
        if p.status in (SUBMITTED, CONFIRMING):
            state, detail = await chain.verify(p, p.tx_hash, ps.payment_confirmations)
            if state == 'paid':
                p.block_number, p.paid_at = detail, t
                set_status(p, PAID, note=f'Verified on-chain in block {detail}')
                quote = db.get(Quote, p.quote_id)
                if quote: quote.status = 'paid'
                db.add(Audit(actor=p.buyer_id, action='buy_payment_verified', reference=p.id))
            elif state == 'confirming':
                p.block_number = detail
                if p.status != CONFIRMING: set_status(p, CONFIRMING, note=f'Mined in block {detail}')
            elif state == 'reverted':
                set_status(p, FAILED, REVERTED)
            elif state == 'mismatch':
                set_status(p, FAILED, f'Transaction does not match this payment: {detail}')
            elif state == 'not_found' and t - (p.submitted_at or t) > ps.payment_tx_timeout:
                set_status(p, FAILED, 'Transaction was not found on Arc Testnet within the timeout')
    except chain.RpcError as exc:
        log.warning('payment %s: chain read failed (%s); will retry', p.id, exc)
    db.commit()
    return p


# ---- views ------------------------------------------------------------------------------------

def explorer(p): return f'{ps.payment_explorer_url}/tx/{p.tx_hash}' if p.tx_hash else None


def portal_view(p):
    return {'id': p.id, 'status': p.status, 'label': LABELS.get(p.status, p.status), 'reason': p.reason,
            'product': p.product_name, 'dealer': p.dealer, 'amount_usdc': f'{p.amount_cents / 100:.2f}',
            'amount_cents': p.amount_cents, 'token_amount': p.token_amount, 'token_address': p.token_address,
            'token_decimals': ps.payment_token_decimals, 'recipient': p.recipient_address, 'payer': p.payer_address,
            'chain_id': p.chain_id, 'network': ps.payment_network_name, 'reference': p.reference,
            'tx_hash': p.tx_hash, 'explorer_url': explorer(p), 'block_number': p.block_number,
            'negotiation_id': p.negotiation_id, 'created': p.created, 'expires': p.expires, 'paid_at': p.paid_at,
            'events': json.loads(p.events or '[]')}


def device_view(p):
    """Shape expected by the Pi (BUY_API.md)."""
    return {'status': p.status, 'payment_id': p.id,
            'message': 'Payment confirmed on-chain' if p.status == PAID else LABELS.get(p.status, p.status),
            'product': p.product_name, 'dealer': p.dealer, 'amount': f'{p.amount_cents / 100:.2f}', 'currency': 'USDC',
            'network': ps.payment_network_name, 'order_id': p.id, 'recipient': p.recipient_address, 'payer': p.payer_address,
            'tx_hash': p.tx_hash, 'explorer_url': explorer(p), 'reason': p.reason}
