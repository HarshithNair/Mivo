"""Raspberry Pi image ingress: bearer auth, image validation, Gemini result passthrough."""
import pytest
from fastapi.testclient import TestClient
from backend.config import settings
from backend.schemas import Identification
from backend.api import device
from backend.api.main import app
from test_core import database

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 100
KEY = 'test-device-key'


@pytest.fixture
def pi(monkeypatch):
    monkeypatch.setattr(settings, 'device_api_key', KEY)
    monkeypatch.setattr(settings, 'gemini_api_key', 'test')
    calls = []
    async def fake(image, mime):
        calls.append((image, mime))
        return Identification(identified=True, name='Studio ANC Headphones', brand='Mivo', confidence=0.9), [{'title': 'Example', 'url': 'https://example.com'}], True
    monkeypatch.setattr(device, 'identify_product', fake)
    with TestClient(app) as c:  # no Origin header, like a real device
        c.calls = calls; yield c


def post(c, body=JPEG, mime='image/jpeg', key=KEY):
    return c.post('/device/identify', content=body, headers={'content-type': mime, 'authorization': f'Bearer {key}'})


def test_identifies_and_matches_catalog(pi):
    r = post(pi); assert r.status_code == 200, r.text
    data = r.json()
    assert data['name'] == 'Studio ANC Headphones' and data['sources'][0]['url'] == 'https://example.com' and data['web_search'] is True
    assert data['catalog_matches'] and all('floor_cents' not in m for m in data['catalog_matches'])
    assert pi.calls == [(JPEG, 'image/jpeg')]


def test_rejects_bad_key(pi):
    assert post(pi, key='wrong').status_code == 401
    assert pi.post('/device/identify', content=JPEG, headers={'content-type': 'image/jpeg'}).status_code == 401


def test_disabled_without_key(pi, monkeypatch):
    monkeypatch.setattr(settings, 'device_api_key', '')
    assert post(pi).status_code == 503


@pytest.mark.parametrize('body,mime', [(JPEG, 'text/plain'), (b'not an image', 'image/jpeg'), (b'RIFF0000WAVE', 'image/webp')])
def test_rejects_non_images(pi, body, mime):
    assert post(pi, body, mime).status_code == 415 and not pi.calls


def test_rejects_oversized(pi):
    assert post(pi, JPEG + b'0' * device.MAX_IMAGE_BYTES).status_code == 413 and not pi.calls


def test_parses_fenced_json():
    from backend.agents.gemini import parse_json_object
    assert parse_json_object('```json\n{"identified": true, "name": "X"}\n```')['name'] == 'X'
    with pytest.raises(ValueError): parse_json_object('no product here')


def test_identification_trims_untrusted_output():
    i = Identification(identified=True, name='n' * 500, key_features=['f'] * 50, confidence=7)
    assert len(i.name) == 120 and len(i.key_features) == 10 and i.confidence == 1.0


def test_falls_back_without_search_when_grounding_quota_is_gone(monkeypatch):
    import asyncio
    from google.genai import errors as genai_errors
    from backend.agents import gemini
    monkeypatch.setattr(settings, 'gemini_api_key', 'test')
    monkeypatch.setattr(gemini, 'search_blocked_until', 0.0)
    async def no_wait(): pass
    monkeypatch.setattr(gemini.pacer, 'wait', no_wait)
    calls = []
    async def attempt(image, mime, search=True):
        calls.append(search)
        if search: raise genai_errors.ClientError(429, {'error': {'code': 429, 'message': 'quota', 'status': 'RESOURCE_EXHAUSTED'}})
        return Identification(identified=True, name='Phone'), []
    monkeypatch.setattr(gemini, 'identify_attempt', attempt)
    ident, sources, web = asyncio.run(gemini.identify_product(b'x', 'image/jpeg'))
    # One grounded try (429 is not retried there), then the ungrounded call.
    assert calls == [True, False] and web is False and ident.name == 'Phone'


def test_other_errors_do_not_fall_back(monkeypatch):
    import asyncio
    from google.genai import errors as genai_errors
    from backend.agents import gemini
    monkeypatch.setattr(settings, 'gemini_api_key', 'test')
    async def attempt(image, mime, search=True):
        raise genai_errors.ClientError(400, {'error': {'code': 400, 'message': 'bad', 'status': 'INVALID_ARGUMENT'}})
    monkeypatch.setattr(gemini, 'identify_attempt', attempt)
    with pytest.raises(genai_errors.ClientError): asyncio.run(gemini.identify_product(b'x', 'image/jpeg'))


def test_identify_prompt_builds():
    from backend.agents.gemini import identify_prompt
    assert 'Google Search' in identify_prompt(True) and 'Google Search' not in identify_prompt(False)
    assert '"low"' in identify_prompt(False) and '<search>' not in identify_prompt(True)


# ---- ?negotiate=true -------------------------------------------------------------------------
from backend.schemas import PriceRange, Proposal, DealerCounters, DealerCounter
from backend.services import negotiation as negotiation_service
from backend.db import SessionLocal
from backend.models import Product, Negotiation, Offer, User
from sqlalchemy import select
import random

BUYER = 'pi-owner@example.com'


@pytest.fixture
def deal(pi, monkeypatch):
    monkeypatch.setattr(settings, 'device_buyer_email', BUYER)
    async def fake(image, mime):
        pi.calls.append((image, mime))
        return Identification(identified=True, name='Apple iPhone 15 Pro', brand='Apple', category='Smartphone',
                              price_range_usd=PriceRange(low=800, high=900), confidence=0.95), [], False
    monkeypatch.setattr(device, 'identify_product', fake)
    pi.rounds = []
    async def counters(data):
        pi.rounds.append(data)
        return DealerCounters(counters=[DealerCounter(dealer=d['dealer'], amount_cents=max(d['private_floor_cents'], d['previous_counter_cents'] - 2000)) for d in data['dealers']])
    async def forbidden(data): raise AssertionError('device negotiations must not make per-agent calls')
    monkeypatch.setattr(negotiation_service, 'dealer_counters', counters)
    monkeypatch.setattr(negotiation_service, 'buyer_proposal', forbidden)
    monkeypatch.setattr(negotiation_service, 'merchant_proposal', forbidden)
    r = pi.post('/auth/register', headers={'origin': 'http://localhost:3000'},
                json={'email': BUYER, 'name': 'Pi owner', 'password': 'correct-horse-battery', 'role': 'buyer'})
    assert r.status_code == 201
    return pi


def negotiate(c, query='negotiate=true'):
    return c.post('/device/identify?' + query, content=JPEG, headers={'content-type': 'image/jpeg', 'authorization': f'Bearer {KEY}'})


def test_negotiates_with_demo_dealers_and_shows_on_website(deal):
    r = negotiate(deal); assert r.status_code == 200, r.text
    n = r.json()['negotiation']
    assert n['status'] == 'completed' and len(n['dealers']) == 3
    assert all(d['name'].endswith(' · Demo') for d in n['dealers'])
    assert n['best_offer'] == n['offers'][0] and n['best_offer']['price_usd'] == min(o['price_usd'] for o in n['offers'])
    assert n['deal_room_url'].endswith('/deal-room?id=' + n['id'])
    with SessionLocal() as db:
        for o in db.scalars(select(Offer).where(Offer.negotiation_id == n['id'])):
            p = db.get(Product, o.product_id)
            assert p.floor_cents <= o.amount_cents <= p.price_cents and not p.listed
    # The website shows it to the configured buyer, starting with the device note.
    deals = deal.get('/negotiations').json()
    assert deals[0]['id'] == n['id'] and 'Raspberry Pi' in deals[0]['messages'][0]['text']
    assert deals[0]['offers'] and all('floor_cents' not in o['product'] for o in deals[0]['offers'])
    # Demo-dealer listings never appear in the public catalog.
    assert all(p['name'] != 'Apple iPhone 15 Pro' for p in deal.get('/products').json())
    # And the buyer can accept the best offer on the website as usual.
    best = deals[0]['offers'][0]['id']
    assert deal.post(f'/offers/{best}/accept', headers={'origin': 'http://localhost:3000'}).status_code == 200


def test_budget_is_passed_through(deal):
    n = negotiate(deal, 'negotiate=true&budget_usd=750').json()['negotiation']
    assert n['budget_usd'] == 750.0
    assert negotiate(deal, 'negotiate=true&budget_usd=0').status_code == 422


def test_negotiate_requires_configured_buyer(deal, monkeypatch):
    monkeypatch.setattr(settings, 'device_buyer_email', '')
    assert negotiate(deal).status_code == 503
    monkeypatch.setattr(settings, 'device_buyer_email', 'nobody@example.com')
    assert negotiate(deal).status_code == 503
    assert not deal.calls  # fails before spending a Gemini call


def test_skips_when_no_price(deal, monkeypatch):
    async def fake(image, mime): return Identification(identified=True, name='Mystery gadget'), [], False
    monkeypatch.setattr(device, 'identify_product', fake)
    r = negotiate(deal).json()
    assert r['negotiation']['status'] == 'skipped' and 'price' in r['negotiation']['reason']


def test_plain_identify_does_not_negotiate(deal):
    assert 'negotiation' not in negotiate(deal, 'negotiate=false').json()


def test_new_scan_retires_previous_scan_listings(deal):
    negotiate(deal); negotiate(deal)
    with SessionLocal() as db:
        live = list(db.scalars(select(Product).where(Product.name == 'Apple iPhone 15 Pro', Product.inventory > 0)))
    assert len(live) == 3


def test_dealer_prices_stay_in_bounds():
    from backend.services import dealers
    assert dealers.reference_cents(None) is None
    assert dealers.reference_cents(PriceRange(low=None, high=-5)) is None
    assert dealers.reference_cents(PriceRange(low=800, high=900)) == 85000
    assert dealers.reference_cents(PriceRange(high=10**9)) == dealers.MAX_CENTS
    with SessionLocal() as db:
        products = dealers.create_listings(db, Identification(identified=True, name='X'), 85000, 3, random.Random(1))
        assert [p.price_cents for p in products] == sorted(p.price_cents for p in products)
        assert all(p.floor_cents < p.price_cents and not p.listed and p.inventory > 0 for p in products)
        db.rollback()



def test_one_gemini_call_per_round(deal):
    n = negotiate(deal).json()['negotiation']
    assert n['status'] == 'completed'
    assert len(deal.calls) == 1 and len(deal.rounds) == settings.device_rounds  # 1 identify + 1 per round
    assert deal.rounds[-1]['final_round'] and not deal.rounds[0]['final_round']
    # Each round's buyer offer is in the prompt; round 2 never goes below round 1.
    assert deal.rounds[1]['buyer_offer_cents'] >= deal.rounds[0]['buyer_offer_cents']


def test_buyer_rule():
    from backend.services.negotiation import buyer_offer
    assert buyer_offer(90000, 100000, None, 100000) == 75000          # anchor 75% of cheapest listing
    assert buyer_offer(90000, 100000, 75000, 85000) == 80000          # halfway toward best counter
    assert buyer_offer(78000, 100000, 75000, 85000) == 78000          # capped by budget
    assert buyer_offer(90000, 100000, 80000, 70000) == 80000          # never retreats


def test_dealer_counters_are_bounded(deal, monkeypatch):
    async def counters(data):
        d = data['dealers']
        # dealer 0 tries to raise its price, dealer 1 goes below floor, dealer 2 is skipped, junk index ignored
        return DealerCounters(counters=[DealerCounter(dealer=0, amount_cents=d[0]['previous_counter_cents'] + 5000),
                                        DealerCounter(dealer=1, amount_cents=d[1]['private_floor_cents'] - 1),
                                        DealerCounter(dealer=7, amount_cents=50000)])
    monkeypatch.setattr(negotiation_service, 'dealer_counters', counters)
    n = negotiate(deal).json()['negotiation']
    assert n['status'] == 'failed' and n['offers'] == []


def test_search_backoff_skips_grounded_attempts(monkeypatch):
    import asyncio
    from google.genai import errors as genai_errors
    from backend.agents import gemini
    monkeypatch.setattr(settings, 'gemini_api_key', 'test')
    monkeypatch.setattr(gemini, 'search_blocked_until', 0.0)
    async def no_wait(): pass
    monkeypatch.setattr(gemini.pacer, 'wait', no_wait)
    calls = []
    async def attempt(image, mime, search=True):
        calls.append(search)
        if search: raise genai_errors.ClientError(429, {'error': {'code': 429, 'message': 'quota', 'status': 'RESOURCE_EXHAUSTED'}})
        return Identification(identified=True, name='Phone'), []
    monkeypatch.setattr(gemini, 'identify_attempt', attempt)
    asyncio.run(gemini.identify_product(b'x', 'image/jpeg'))
    asyncio.run(gemini.identify_product(b'x', 'image/jpeg'))
    assert calls == [True, False, False]  # second scan goes straight to the no-search call
