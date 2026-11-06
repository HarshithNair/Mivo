"""Drop-in negotiation agents: same signatures and return types as backend.agents.gemini.

Order per decision: 0G Compute (if ZEROG_API_KEY set) -> validate -> deterministic price rules.
On any 0G failure (timeout, HTTP error, invalid output) the existing Gemini agent decides instead,
and the decision log records why. If both fail the exception propagates, so the existing engine
drops that merchant / fails the negotiation safely: nothing is ever invented.
"""
import json
import logging
from contextvars import ContextVar
from backend.config import settings
from backend.db import SessionLocal
from backend.schemas import Proposal, DealerCounters, DealerCounter
from backend.agents import gemini
from backend.integrations.zerog import compute, policy
from backend.integrations.zerog.config import zerog_settings as zs
from backend.integrations.zerog.models import ZeroGDecision

log = logging.getLogger('mivo.zerog')
# Set by the negotiation engine so each decision is filed under its negotiation (session id).
negotiation_session: ContextVar[str | None] = ContextVar('mivo_negotiation_session', default=None)


def record(role, round_no, meta, output=None, result=None, fallback=None):
    try:
        with SessionLocal() as db:
            db.add(ZeroGDecision(negotiation_id=negotiation_session.get(), role=role, round=round_no,
                                 provider=meta.get('provider', '0g'), model=meta.get('model'), request_id=meta.get('request_id'),
                                 provider_address=meta.get('provider_address'),
                                 provider_identity=json.dumps(meta['provider_identity']) if meta.get('provider_identity') is not None else None,
                                 tee_verified=meta.get('tee_verified'), latency_ms=meta.get('latency_ms'), attempts=meta.get('attempts', 1),
                                 model_output=json.dumps(output) if output is not None else None,
                                 result=json.dumps(result) if result is not None else None, fallback_reason=fallback))
            db.commit()
    except Exception:  # the log must never break a negotiation
        log.exception('could not record 0G decision')


async def on_zerog(role, round_no, messages, model_cls):
    """Run one 0G decision; returns (validated move, meta) or raises compute.ZeroGError."""
    raw, meta = await compute.chat_json(messages, client_request_id=negotiation_session.get())
    try: move = policy.validate(model_cls, raw)
    except ValueError as exc: raise compute.ZeroGError(str(exc), {**meta, 'raw': json.dumps(raw)[:300]}) from None
    return move, meta, raw


async def fallback(role, round_no, exc, call):
    meta = getattr(exc, 'meta', {}) or {}
    log.warning('0G %s decision failed (%s); using Gemini', role, exc)
    result = await call()
    record(role, round_no, {'provider': 'gemini', 'model': settings.gemini_model, 'request_id': None},
           result=result.model_dump(), fallback=f'{exc}' + (f' [0G request {meta["request_id"]}]' if meta.get('request_id') else ''))
    return result


async def merchant_proposal(data):
    if not zs.active: return await gemini.merchant_proposal(data)
    try:
        messages, last = policy.merchant_prompt(data, settings.negotiation_rounds)
        move, meta, raw = await on_zerog('merchant', data['round'], messages, policy.MerchantMove)
    except compute.ZeroGError as exc:
        return await fallback('merchant', data['round'], exc, lambda: gemini.merchant_proposal(data))
    price = policy.merchant_price(move, last, data['private_floor_cents'], data['buyer_offer_cents'])
    record('merchant', data['round'], meta, output=raw, result={'amount_cents': price})
    return Proposal(amount_cents=price)


async def buyer_proposal(data):
    if not zs.active: return await gemini.buyer_proposal(data)
    try:
        move, meta, raw = await on_zerog('buyer', data['round'], policy.buyer_prompt(data, settings.negotiation_rounds), policy.BuyerMove)
    except compute.ZeroGError as exc:
        return await fallback('buyer', data['round'], exc, lambda: gemini.buyer_proposal(data))
    price = policy.buyer_price(move, data['budget_cents'])
    record('buyer', data['round'], meta, output=raw, result={'amount_cents': price})
    return Proposal(amount_cents=price)


async def dealer_counters(data):
    if not zs.active: return await gemini.dealer_counters(data)
    try:
        moves, meta, raw = await on_zerog('dealers', data['round'], policy.dealers_prompt(data), policy.DealerMoves)
    except compute.ZeroGError as exc:
        return await fallback('dealers', data['round'], exc, lambda: gemini.dealer_counters(data))
    prices = policy.dealer_prices(moves, data)
    record('dealers', data['round'], meta, output=raw, result={str(k): v for k, v in prices.items()})
    return DealerCounters(counters=[DealerCounter(dealer=i, amount_cents=p) for i, p in prices.items()])
