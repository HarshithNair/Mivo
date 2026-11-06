import asyncio
import pytest
from sqlalchemy import select
from backend.models import Negotiation, Product, User, Offer, Message
from backend.db import SessionLocal
from backend.schemas import Proposal
from backend.services import negotiation as service
from test_core import database

def job():
    with SessionLocal() as db:
        buyer=User(name='Buyer',email='agent@example.com',role='buyer',password_hash='not-a-login');db.add(buyer);db.flush()
        p=db.scalar(select(Product).where(Product.name=='Studio ANC Headphones'))
        n=Negotiation(buyer_id=buyer.id,product_id=p.id,budget_cents=14000);db.add(n);db.commit();return n.id

def test_valid_agents_persist_real_events(monkeypatch):
    # Pin the round count so the expected event total does not drift with configured depth.
    rounds=4;merchants=3
    monkeypatch.setattr(service,'MAX_ROUNDS',rounds)
    async def buyer(data):return Proposal(amount_cents=12000)
    async def merchant(data):return Proposal(amount_cents=data['private_floor_cents']+100)
    monkeypatch.setattr(service,'buyer_proposal',buyer);monkeypatch.setattr(service,'merchant_proposal',merchant)
    nid=job();asyncio.run(service.run_negotiation(nid))
    with SessionLocal() as db:
        assert db.get(Negotiation,nid).status=='completed'
        offers=list(db.scalars(select(Offer)));assert len(offers)==3
        assert all(o.amount_cents>=db.get(Product,o.product_id).floor_cents for o in offers)
        messages=list(db.scalars(select(Message)));assert len(messages)==rounds*(1+merchants)+1
        assert len({m.sequence for m in messages})==len(messages)
    asyncio.run(service.run_negotiation(nid))
    with SessionLocal() as db: assert len(list(db.scalars(select(Offer))))==3

def test_invalid_model_price_fails_closed(monkeypatch):
    async def buyer(data):return Proposal(amount_cents=12000)
    async def merchant(data):return Proposal(amount_cents=1)
    monkeypatch.setattr(service,'buyer_proposal',buyer);monkeypatch.setattr(service,'merchant_proposal',merchant)
    nid=job();asyncio.run(service.run_negotiation(nid))
    with SessionLocal() as db:
        assert db.get(Negotiation,nid).status=='failed'
        assert list(db.scalars(select(Offer)))==[]

def test_cancel_during_agent_response(monkeypatch):
    nid=job()
    async def buyer(data):return Proposal(amount_cents=12000)
    async def merchant(data):
        with SessionLocal() as db:
            n=db.get(Negotiation,nid);n.status='cancelled';db.commit()
        return Proposal(amount_cents=13000)
    monkeypatch.setattr(service,'buyer_proposal',buyer);monkeypatch.setattr(service,'merchant_proposal',merchant)
    asyncio.run(service.run_negotiation(nid))
    with SessionLocal() as db:
        assert db.get(Negotiation,nid).status=='cancelled'
        assert list(db.scalars(select(Offer)))==[]
