import os,tempfile
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.models import Base, Product, Negotiation, Offer, now
from backend.db import engine, SessionLocal
from backend.api.main import app, attempts
from backend.services.negotiation import validate_price
from backend.seed import seed
from backend.config import settings
@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); attempts.clear(); seed()
@pytest.fixture
def client():
    with TestClient(app,headers={'origin':'http://localhost:3000'}) as c: yield c

def register(c,role='buyer',email='buyer@example.com'):
    r=c.post('/auth/register',json={'email':email,'name':'Test','password':'correct-horse-battery','role':role}); assert r.status_code==201; return r.json()
def test_auth(client):
    u=register(client); assert client.get('/auth/me').json()['id']==u['id']
    client.post('/auth/logout'); assert client.get('/auth/me').status_code==401
    assert client.post('/auth/login',json={'email':'buyer@example.com','password':'wrong-password-long'}).status_code==401
    assert client.post('/auth/login',json={'email':'buyer@example.com','password':'correct-horse-battery'}).status_code==200
def test_permissions(client):
    assert client.post('/auth/register',headers={'origin':'https://evil.example'},json={}).status_code==403
    register(client); assert client.get('/merchant/products').status_code==403
def test_catalog(client):
    products=client.get('/products').json(); assert len(products)>=10
    assert len({p['merchant_id'] for p in products})==3
    assert all('floor_cents' not in p for p in products)
    assert all(p['price_cents']<=10000 for p in client.get('/products?max_price=10000').json())
    assert client.get('/products?q=impossible-product').json()==[]
def test_merchant_ownership(client):
    register(client,'merchant')
    data={'name':'Test headphones','category':'Headphones','description':'Testing product','price_cents':10000,'floor_cents':8000,'inventory':4}
    r=client.post('/merchant/products',json=data); assert r.status_code==201; pid=r.json()['id']
    assert client.put('/merchant/products/'+pid,json={**data,'floor_cents':11000}).status_code==422
    client.post('/auth/logout'); register(client,'merchant','other@example.com')
    assert client.put('/merchant/products/'+pid,json=data).status_code==404
    assert client.delete('/merchant/products/'+pid).status_code==404
@pytest.mark.parametrize('amount',[7999,10001,True,9000.5,-1])
def test_price_constraints(amount):
    with pytest.raises(ValueError): validate_price(amount,8000,10000)
def test_valid_price(): assert validate_price(8000,8000,10000)==8000

def make_offer(buyer,expired=False):
    with SessionLocal() as db:
        p=db.scalar(select(Product)); n=Negotiation(buyer_id=buyer['id'],product_id=p.id,budget_cents=p.price_cents,status='completed'); db.add(n); db.flush()
        o=Offer(negotiation_id=n.id,product_id=p.id,amount_cents=p.price_cents,expires=now()+(-1 if expired else 600)); db.add(o); db.commit(); return o.id,n.id
def test_quote(client):
    buyer=register(client); oid,nid=make_offer(buyer)
    first=client.post(f'/offers/{oid}/accept'); assert first.status_code==200
    assert client.post(f'/offers/{oid}/accept').json()==first.json()
    assert client.get('/quotes/'+first.json()['id']).json()['payment_enabled'] is False
    client.post('/auth/logout'); register(client,email='intruder@example.com')
    assert client.get('/negotiations/'+nid).status_code==404
    assert client.post(f'/offers/{oid}/accept').status_code==404
def test_expiry(client):
    oid,_=make_offer(register(client),True); assert client.post(f'/offers/{oid}/accept').status_code==409
def test_no_fake_ai(client, monkeypatch):
    # Force the unconfigured state so the fail-closed guarantee is tested regardless of local .env.
    monkeypatch.setattr(settings,'gemini_api_key','')
    register(client); p=client.get('/products').json()[0]
    assert client.post('/negotiations',json={'product_id':p['id'],'budget_cents':10000}).status_code==503
    assert client.get('/negotiations').json()==[]

def test_password_hash_and_expired_session(client):
    from backend.models import User,Session
    from backend.services.auth import token_hash
    register(client)
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email=='buyer@example.com'))
        assert user.password_hash.startswith('$argon2id$')
        session=db.get(Session,token_hash(client.cookies.get('mivo_session')))
        session.expires=now()-1;db.commit()
    assert client.get('/auth/me').status_code==401

def test_quote_policy_change_rejected(client):
    buyer=register(client);oid,_=make_offer(buyer)
    with SessionLocal() as db:
        offer=db.get(Offer,oid);p=db.get(Product,offer.product_id);p.floor_cents=offer.amount_cents+1;db.commit()
    assert client.post(f'/offers/{oid}/accept').status_code==409

def test_unauthorized_websocket(client):
    from starlette.websockets import WebSocketDisconnect
    buyer=register(client);_,nid=make_offer(buyer)
    client.post('/auth/logout')
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/negotiations/'+nid): pass
