"""Sanitized negotiation evidence for public 0G Storage.

Included: negotiation id, product reference, public offer/counter history with timestamps,
accepted price, 0G request ids / provider addresses / models per decision, payment tx hash.
Excluded by construction: merchant floors, buyer budget, user ids/emails/names, wallet addresses,
model free-text messages.
"""
import hashlib
import json
from sqlalchemy import select
from backend.models import Negotiation, Product, Message, Offer, Quote, User


def canonical(obj): return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def content_hash(obj): return '0x' + hashlib.sha256(canonical(obj)).hexdigest()


def build(db, nid):
    from backend.integrations.zerog.models import ZeroGDecision
    n = db.get(Negotiation, nid)
    if not n: return None
    product = db.get(Product, n.product_id)
    merchant = lambda mid: db.get(User, mid).name if mid else None  # demo dealer display names are public labels
    messages = [{'seq': m.sequence, 'role': m.role, 'party': merchant(m.merchant_id) if m.role == 'merchant' else m.role,
                 'amount_usd': m.amount_cents / 100 if m.amount_cents is not None else None, 'at': m.created}
                for m in db.scalars(select(Message).where(Message.negotiation_id == nid).order_by(Message.sequence)) if m.role != 'system']
    offers = [{'dealer': merchant(db.get(Product, o.product_id).merchant_id), 'amount_usd': o.amount_cents / 100, 'expires': o.expires}
              for o in db.scalars(select(Offer).where(Offer.negotiation_id == nid).order_by(Offer.amount_cents))]
    quote = db.scalar(select(Quote).where(Quote.negotiation_id == nid))
    decisions = [{'role': d.role, 'round': d.round, 'provider': d.provider, 'model': d.model, 'request_id': d.request_id,
                  'provider_address': d.provider_address, 'tee_verified': d.tee_verified, 'fallback': bool(d.fallback_reason),
                  'at': d.created}
                 for d in db.scalars(select(ZeroGDecision).where(ZeroGDecision.negotiation_id == nid).order_by(ZeroGDecision.created))]
    payment = None
    try:
        from backend.buy_payments.models import BuyPayment
        p = db.scalar(select(BuyPayment).where(BuyPayment.negotiation_id == nid, BuyPayment.status == 'paid'))
        if p: payment = {'network': 'Arc Testnet', 'chain_id': p.chain_id, 'tx_hash': p.tx_hash, 'amount_usdc': p.amount_cents / 100, 'paid_at': p.paid_at}
    except Exception:
        payment = None
    return {'schema': 'mivo.negotiation-evidence/1', 'negotiation_id': n.id, 'status': n.status, 'created': n.created,
            'product': {'id': product.id, 'name': product.name, 'category': product.category},
            'history': messages, 'final_offers': offers,
            'accepted': {'amount_usd': quote.amount_cents / 100, 'status': quote.status} if quote else None,
            'ai_decisions': decisions, 'payment': payment}
