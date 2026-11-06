"""0G integration: router client, privacy-preserving policy, agents with Gemini fallback, evidence.
HTTP to the 0G router is mocked here; live calls are in scripts/zerog_live_check.py."""
import asyncio
import json
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.config import settings
from backend.db import SessionLocal
from backend.models import Negotiation, Product, User, Offer, Message, now
from backend.schemas import Proposal, DealerCounters, DealerCounter
from backend.integrations.zerog import compute, policy, agents, evidence
from backend.integrations.zerog.config import zerog_settings as zs
from backend.integrations.zerog.models import ZeroGDecision, ZeroGEvidence
from backend.integrations.zerog.api import router
from backend.services import negotiation as engine
from test_core import database

FLOOR, LISTING = 11900, 14900
REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture
def zg(monkeypatch):
    monkeypatch.setattr(zs, 'zerog_api_key', 'sk-test'); monkeypatch.setattr(zs, 'zerog_enabled', True)
    monkeypatch.setattr(zs, 'zerog_retries', 1)
    async def no_sleep(*_): pass
    monkeypatch.setattr(compute.asyncio, 'sleep', no_sleep)
    token = agents.negotiation_session.set(None)
    yield
    agents.negotiation_session.reset(token)


def mock_router(monkeypatch, responses, seen=None):
    """responses: list of (status, json_body | Exception)."""
    queue = list(responses)
    def handler(request):
        if seen is not None: seen.append(request)
        status, body = queue.pop(0)
        if isinstance(body, Exception): raise body
        return httpx.Response(status, json=body, headers={'x-request-id': 'hdr-req'})
    monkeypatch.setattr(compute.httpx, 'AsyncClient', lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw))


def ok(content, request_id='req-0g-1', provider='0xProvider'):
    return 200, {'id': 'chatcmpl-1', 'model': '0gm-1.0-35b-a3b', 'choices': [{'message': {'content': content}}],
                 'x_0g_trace': {'request_id': request_id, 'provider': provider, 'tee_verified': True}, 'usage': {'total_tokens': 42}}


# ---- router client ----------------------------------------------------------------------------

def test_client_returns_json_and_0g_metadata(zg, monkeypatch):
    seen = []
    mock_router(monkeypatch, [ok('```json\n{"decision":"counter","concession":0.3,"message":"hi"}\n```')], seen)
    raw, meta = asyncio.run(compute.chat_json([{'role': 'user', 'content': 'x'}], client_request_id='neg-1'))
    assert raw['concession'] == 0.3
    assert meta['request_id'] == 'req-0g-1' and meta['provider_address'] == '0xProvider' and meta['tee_verified'] is True
    req = seen[0]
    assert req.headers['authorization'] == 'Bearer sk-test' and req.headers['x-client-request-id'] == 'neg-1'
    body = json.loads(req.content)
    assert body['model'] == '0gm-1.0-35b-a3b' and body['response_format'] == {'type': 'json_object'}


def test_client_retries_rate_limit(zg, monkeypatch):
    mock_router(monkeypatch, [(429, {'error': {'message': 'slow down'}}), ok('{"offer_usd": 100}')])
    raw, meta = asyncio.run(compute.chat_json([]))
    assert raw == {'offer_usd': 100} and meta['attempts'] == 2


def test_client_timeout_and_invalid_output_raise(zg, monkeypatch):
    mock_router(monkeypatch, [(200, httpx.ReadTimeout('t')), (200, httpx.ReadTimeout('t'))])
    with pytest.raises(compute.ZeroGError, match='timed out'): asyncio.run(compute.chat_json([]))
    mock_router(monkeypatch, [ok('I think 120 dollars'), ok('still prose')])
    with pytest.raises(compute.ZeroGError, match='invalid model output'): asyncio.run(compute.chat_json([]))
    mock_router(monkeypatch, [(401, {'error': {'message': 'bad key'}})])
    with pytest.raises(compute.ZeroGError, match='401'): asyncio.run(compute.chat_json([]))


def test_client_requires_key(monkeypatch):
    monkeypatch.setattr(zs, 'zerog_api_key', '')
    with pytest.raises(compute.ZeroGError, match='ZEROG_API_KEY'): asyncio.run(compute.chat_json([]))


# ---- policy: privacy + deterministic bounds ----------------------------------------------------

MERCHANT_DATA = {'buyer_offer_cents': 10000, 'listing_cents': LISTING, 'private_floor_cents': FLOOR, 'inventory': 9, 'round': 2,
                 'history': [{'merchant_id': 'm', 'amount_cents': 14000, 'round': 1}]}


def test_prompts_never_contain_private_floor_or_budget_keys():
    msgs, _ = policy.merchant_prompt(MERCHANT_DATA, 2)
    text = json.dumps(msgs)
    assert str(FLOOR) not in text and '119.0' not in text and 'floor' not in msgs[1]['content']
    dealers = {'buyer_offer_cents': 10000, 'round': 1, 'final_round': False,
               'dealers': [{'dealer': 0, 'listing_cents': LISTING, 'private_floor_cents': FLOOR, 'inventory': 3, 'previous_counter_cents': LISTING}]}
    text = json.dumps(policy.dealers_prompt(dealers))
    assert str(FLOOR) not in text and '119.0' not in text and 'private_floor' not in text


@pytest.mark.parametrize('decision,concession', [('counter', 0), ('counter', 0.5), ('counter', 1), ('accept', 1), ('accept', 0)])
def test_merchant_price_always_within_floor_and_last(decision, concession):
    move = policy.MerchantMove(decision=decision, concession=concession)
    for buyer in (5000, 11899, 11900, 13000, 20000):
        price = policy.merchant_price(move, 14000, FLOOR, buyer)
        assert FLOOR <= price <= 14000


def test_accept_below_floor_is_not_a_sale():
    assert policy.merchant_price(policy.MerchantMove(decision='accept', concession=0), 14000, FLOOR, 9000) == 14000


@pytest.mark.parametrize('raw', [{'decision': 'counter', 'concession': 5}, {'decision': 'sell now', 'concession': 0.2},
                                 {'concession': 0.2}, {'decision': 'counter', 'concession': 'lots'}, []])
def test_invalid_model_output_is_rejected(raw):
    with pytest.raises(ValueError): policy.validate(policy.MerchantMove, raw)


def test_buyer_never_exceeds_budget():
    assert policy.buyer_price(policy.BuyerMove(offer_usd=999), 12000) == 12000


# ---- agents: 0G first, Gemini fallback, decision log --------------------------------------------

def neg_id():
    with SessionLocal() as db:
        u = User(email='zg@example.com', name='ZG', role='buyer', password_hash='x'); db.add(u); db.flush()
        p = db.scalar(select(Product)); n = Negotiation(buyer_id=u.id, product_id=p.id, budget_cents=12000)
        db.add(n); db.commit(); return n.id


def decisions(nid=None):
    with SessionLocal() as db:
        q = select(ZeroGDecision).order_by(ZeroGDecision.created)
        if nid: q = q.where(ZeroGDecision.negotiation_id == nid)
        return list(db.scalars(q))


def test_merchant_decision_on_0g_is_logged_and_floor_enforced(zg, monkeypatch):
    nid = neg_id(); agents.negotiation_session.set(nid)
    mock_router(monkeypatch, [ok('{"decision":"counter","concession":1,"message":"best I can do"}', request_id='req-abc')])
    price = asyncio.run(agents.merchant_proposal(MERCHANT_DATA)).amount_cents
    assert price == FLOOR  # model asked for the maximum concession; the server stopped at the floor
    d = decisions(nid)[0]
    assert d.provider == '0g' and d.request_id == 'req-abc' and d.role == 'merchant' and d.fallback_reason is None
    assert json.loads(d.result) == {'amount_cents': FLOOR} and 'floor' not in (d.model_output or '')


def test_invalid_0g_output_falls_back_to_gemini(zg, monkeypatch):
    mock_router(monkeypatch, [ok('{"decision":"counter","concession":7}'), ok('{"decision":"counter","concession":7}')])
    async def gem(data): return Proposal(amount_cents=13000)
    monkeypatch.setattr(agents.gemini, 'merchant_proposal', gem)
    assert asyncio.run(agents.merchant_proposal(MERCHANT_DATA)).amount_cents == 13000
    d = decisions()[-1]
    assert d.provider == 'gemini' and 'invalid model output' in d.fallback_reason and 'req-0g-1' in d.fallback_reason


def test_0g_timeout_falls_back_and_double_failure_raises(zg, monkeypatch):
    mock_router(monkeypatch, [(200, httpx.ReadTimeout('t'))] * 2)
    async def gem(data): return Proposal(amount_cents=12500)
    monkeypatch.setattr(agents.gemini, 'buyer_proposal', gem)
    data = {'budget_cents': 12000, 'listing_cents': LISTING, 'round': 1, 'history': []}
    assert asyncio.run(agents.buyer_proposal(data)).amount_cents == 12500
    assert 'timed out' in decisions()[-1].fallback_reason
    mock_router(monkeypatch, [(200, httpx.ReadTimeout('t'))] * 2)
    async def broken(data): raise RuntimeError('Gemini is not configured')
    monkeypatch.setattr(agents.gemini, 'buyer_proposal', broken)
    with pytest.raises(RuntimeError): asyncio.run(agents.buyer_proposal(data))  # safe stop: nothing invented


def test_inactive_uses_existing_gemini_and_logs_nothing(monkeypatch):
    monkeypatch.setattr(zs, 'zerog_api_key', '')
    async def gem(data): return Proposal(amount_cents=1)
    monkeypatch.setattr(agents.gemini, 'merchant_proposal', gem)
    assert asyncio.run(agents.merchant_proposal(MERCHANT_DATA)).amount_cents == 1 and decisions() == []


def test_dealer_round_one_call_bounded_prices(zg, monkeypatch):
    data = {'buyer_offer_cents': 10000, 'round': 2, 'final_round': True,
            'dealers': [{'dealer': 0, 'listing_cents': 15000, 'private_floor_cents': 12000, 'inventory': 9, 'previous_counter_cents': 14000},
                        {'dealer': 1, 'listing_cents': 15500, 'private_floor_cents': 12500, 'inventory': 1, 'previous_counter_cents': 15000}]}
    mock_router(monkeypatch, [ok(json.dumps({'counters': [{'dealer': 0, 'decision': 'counter', 'concession': 1},
                                                           {'dealer': 1, 'decision': 'counter', 'concession': 0.5},
                                                           {'dealer': 9, 'decision': 'counter', 'concession': 1}]}))])
    out = {c.dealer: c.amount_cents for c in asyncio.run(agents.dealer_counters(data)).counters}
    assert out == {0: 12000, 1: 13750}


def test_full_device_negotiation_through_0g_adapter(zg, monkeypatch):
    """Product -> buyer offer -> dealers (0G) -> counter -> final round -> valid offers, all logged."""
    with SessionLocal() as db:
        u = User(email='zg2@example.com', name='ZG', role='buyer', password_hash='x'); db.add(u); db.flush()
        products = list(db.scalars(select(Product).where(Product.name == 'Studio ANC Headphones')))
        n = Negotiation(buyer_id=u.id, product_id=products[0].id, budget_cents=12500); db.add(n); db.commit()
        nid, ids, floors = n.id, [p.id for p in products], {p.id: (p.floor_cents, p.price_cents) for p in products}
    replies = [ok(json.dumps({'counters': [{'dealer': i, 'decision': 'counter', 'concession': c} for i in range(len(ids))]}), request_id=f'req-r{r}')
               for r, c in ((1, 0.4), (2, 1))]
    mock_router(monkeypatch, replies)
    monkeypatch.setattr(engine, 'dealer_counters', agents.dealer_counters)
    agents.negotiation_session.set(nid)
    asyncio.run(engine.run_device_negotiation(nid, ids, rounds=2))
    with SessionLocal() as db:
        assert db.get(Negotiation, nid).status == 'completed'
        offers = list(db.scalars(select(Offer).where(Offer.negotiation_id == nid)))
        assert len(offers) == len(ids) and all(floors[o.product_id][0] <= o.amount_cents <= floors[o.product_id][1] for o in offers)
    log = decisions(nid)
    assert [d.request_id for d in log] == ['req-r1', 'req-r2'] and all(d.provider == '0g' for d in log)


# ---- evidence ---------------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(settings, 'device_api_key', 'dk')
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as c: yield c


def test_evidence_is_sanitized_and_hash_checked(api):
    with SessionLocal() as db:
        u = User(email='secret-buyer@example.com', name='Secret Name', role='buyer', password_hash='x'); db.add(u); db.flush()
        p = db.scalar(select(Product).where(Product.name == 'Studio ANC Headphones'))
        n = Negotiation(buyer_id=u.id, product_id=p.id, budget_cents=12345, status='completed'); db.add(n); db.flush()
        db.add(Message(negotiation_id=n.id, sequence=1, role='buyer', text='Round 1', amount_cents=11000))
        db.add(Offer(negotiation_id=n.id, product_id=p.id, amount_cents=13000, expires=now() + 600))
        db.add(ZeroGDecision(negotiation_id=n.id, role='dealers', round=1, provider='0g', model='0gm', request_id='req-x', model_output='{}'))
        db.commit(); nid, floor, uid_ = n.id, p.floor_cents, u.id
    h = {'authorization': 'Bearer dk'}
    r = api.get(f'/device/zerog/evidence/{nid}', headers=h).json()
    text = json.dumps(r)
    for secret in ('secret-buyer@example.com', 'Secret Name', uid_, '123.45', str(floor), 'floor', 'budget'):
        assert secret not in text, secret
    assert r['evidence']['ai_decisions'][0]['request_id'] == 'req-x' and r['content_hash'] == evidence.content_hash(r['evidence'])
    assert api.get(f'/device/zerog/evidence/{nid}', headers={'authorization': 'Bearer no'}).status_code == 401
    good = {'content_hash': r['content_hash'], 'root_hash': '0x' + 'a' * 64, 'tx_hash': '0x' + 'b' * 64, 'verified': True}
    assert api.post(f'/device/zerog/evidence/{nid}/stored', headers=h, json={**good, 'verified': False}).status_code == 422
    assert api.post(f'/device/zerog/evidence/{nid}/stored', headers=h, json={**good, 'content_hash': '0x' + 'c' * 64}).status_code == 409
    assert api.post(f'/device/zerog/evidence/{nid}/stored', headers=h, json=good).status_code == 200
    with SessionLocal() as db: assert db.scalar(select(ZeroGEvidence).where(ZeroGEvidence.negotiation_id == nid)).root_hash == '0x' + 'a' * 64


def test_engine_is_wired_and_sets_session_itself(zg, monkeypatch):
    assert engine.dealer_counters is agents.dealer_counters and engine.merchant_proposal is agents.merchant_proposal
    with SessionLocal() as db:
        u = User(email='zg3@example.com', name='ZG', role='buyer', password_hash='x'); db.add(u); db.flush()
        products = list(db.scalars(select(Product).where(Product.name == 'Studio ANC Headphones')))
        n = Negotiation(buyer_id=u.id, product_id=products[0].id, budget_cents=12500); db.add(n); db.commit()
        nid, ids = n.id, [p.id for p in products]
    mock_router(monkeypatch, [ok(json.dumps({'counters': [{'dealer': i, 'decision': 'counter', 'concession': 0.5} for i in range(len(ids))]}), request_id='req-wired')])
    asyncio.run(engine.run_device_negotiation(nid, ids, rounds=1))  # no manual session: the engine sets it
    assert [d.request_id for d in decisions(nid)] == ['req-wired']
