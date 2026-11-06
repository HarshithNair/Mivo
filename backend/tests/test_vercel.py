"""Serverless (Vercel) behaviour: /api prefix, client-driven runs, stale expiry, origins."""
import pytest
from fastapi.testclient import TestClient
from backend.config import Settings, settings
from backend.db import SessionLocal
from backend.models import Negotiation, Product, now
from backend.schemas import Proposal
from backend.services import negotiation as service
from backend.vercel_app import app as vercel_app
from test_core import database, register


@pytest.fixture
def serverless(monkeypatch):
    monkeypatch.setattr(settings, 'vercel', True)
    monkeypatch.setattr(settings, 'gemini_api_key', 'test-key')
    monkeypatch.setattr(settings, 'vercel_url', 'mivo-git-abc.vercel.app')
    async def buyer(data): return Proposal(amount_cents=12000)
    async def merchant(data): return Proposal(amount_cents=data['private_floor_cents'] + 100)
    monkeypatch.setattr(service, 'buyer_proposal', buyer)
    monkeypatch.setattr(service, 'merchant_proposal', merchant)
    with TestClient(vercel_app, base_url='http://testserver/api', headers={'origin': 'http://localhost:3000'}) as c:
        yield c


def start(c):
    register(c)
    p = next(p for p in c.get('/products').json() if p['name'] == 'Studio ANC Headphones')
    r = c.post('/negotiations', json={'product_id': p['id'], 'budget_cents': 14000})
    assert r.status_code == 201
    return r.json()


def test_prefix_is_stripped(serverless):
    assert serverless.get('/health').status_code == 200


def test_client_driven_run(serverless):
    body = start(serverless)
    assert body['run'] is True
    assert serverless.get('/negotiations/' + body['id']).json()['status'] == 'pending'
    assert serverless.post(f"/negotiations/{body['id']}/run").json()['status'] == 'completed'
    # A repeat call must not start a second negotiation.
    assert serverless.post(f"/negotiations/{body['id']}/run").json()['status'] == 'completed'
    assert serverless.get('/negotiations/' + body['id']).json()['offers']


def test_run_requires_owner(serverless):
    body = start(serverless)
    serverless.post('/auth/logout'); register(serverless, email='intruder@example.com')
    assert serverless.post(f"/negotiations/{body['id']}/run").status_code == 404


def test_stale_negotiations_expire(serverless):
    body = start(serverless)
    with SessionLocal() as db:
        db.get(Negotiation, body['id']).created = now() - settings.negotiation_deadline - 120; db.commit()
    assert serverless.get('/negotiations/' + body['id']).json()['status'] == 'failed'


def test_preview_origin_allowed(serverless):
    assert serverless.post('/auth/logout', headers={'origin': 'https://mivo-git-abc.vercel.app'}).status_code == 200
    assert serverless.post('/auth/logout', headers={'origin': 'https://evil.example'}).status_code == 403


def test_vercel_defaults(monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_PROJECT_PRODUCTION_URL', 'mivo.vercel.app')
    monkeypatch.delenv('APP_ORIGIN', raising=False)
    s = Settings(_env_file=None, database_url='postgres://u:p@h/db')
    assert s.app_origin == 'https://mivo.vercel.app' and s.cookie_secure
    assert s.sqlalchemy_url == 'postgresql+psycopg://u:p@h/db'


def test_same_host_origin_allowed(serverless):
    # Any domain the project answers on works, as long as Origin matches the request host.
    h = {'origin': 'https://mivo-team.vercel.app', 'x-forwarded-host': 'mivo-team.vercel.app'}
    assert serverless.post('/auth/logout', headers=h).status_code == 200
    h = {'origin': 'https://evil.example', 'x-forwarded-host': 'mivo-team.vercel.app'}
    assert serverless.post('/auth/logout', headers=h).status_code == 403
    h = {'origin': 'http://mivo-team.vercel.app', 'x-forwarded-host': 'mivo-team.vercel.app'}
    assert serverless.post('/auth/logout', headers=h).status_code == 403


def test_same_host_rule_is_vercel_only(serverless, monkeypatch):
    monkeypatch.setattr(settings, 'vercel', False)
    h = {'origin': 'https://mivo-team.vercel.app', 'x-forwarded-host': 'mivo-team.vercel.app'}
    assert serverless.post('/auth/logout', headers=h).status_code == 403
