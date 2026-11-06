#!/usr/bin/env python3
"""Live 0G Compute check: real router calls, then a real MIVO negotiation decided on 0G.

    ZEROG_API_KEY=sk-... .venv/bin/python scripts/zerog_live_check.py

Runs on a throwaway SQLite catalog (never your real database). Prints every 0G request id,
provider address and model so the run can be checked against the 0G dashboard.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(tempfile.mkdtemp(prefix='mivo-0g-')) / 'live.db')

from sqlalchemy import select  # noqa: E402
from backend.db import engine as db_engine, SessionLocal  # noqa: E402
from backend.models import Base, User, Product, Negotiation, Offer, Message  # noqa: E402
from backend.seed import seed  # noqa: E402
from backend.integrations.zerog import compute, policy, agents  # noqa: E402
from backend.integrations.zerog.config import zerog_settings as zs  # noqa: E402
from backend.integrations.zerog.models import ZeroGDecision  # noqa: E402
from backend.services import negotiation as engine  # noqa: E402


async def main():
    if not zs.zerog_api_key: sys.exit('Set ZEROG_API_KEY (an sk- key from the 0G Compute Router).')
    print(f'router {zs.zerog_router_url} · model {zs.zerog_model}')
    models = await compute.list_models()
    print('model listed on router:', any(m.get('id') == zs.zerog_model for m in models), f'({len(models)} models)')

    # 1. One raw inference: a merchant decision from public numbers only.
    sample = {'buyer_offer_cents': 11000, 'listing_cents': 14900, 'private_floor_cents': 11900, 'inventory': 9, 'round': 1, 'history': []}
    messages, last = policy.merchant_prompt(sample, 2)
    raw, meta = await compute.chat_json(messages, client_request_id='mivo-live-check')
    move = policy.validate(policy.MerchantMove, raw)
    print('\n[1] raw 0G inference')
    print('    request_id      ', meta.get('request_id'))
    print('    provider        ', meta.get('provider_address'), '| tee_verified', meta.get('tee_verified'))
    print('    model / latency ', meta.get('model'), f"{meta.get('latency_ms')} ms", '| usage', meta.get('usage'))
    print('    model output    ', json.dumps(raw))
    print('    server price    ', policy.merchant_price(move, last, sample['private_floor_cents'], sample['buyer_offer_cents']) / 100,
          '(floor 119.00 enforced server-side; never sent)')

    # 2. A real MIVO negotiation where every dealer decision comes from 0G.
    Base.metadata.create_all(db_engine); seed()
    with SessionLocal() as db:
        buyer = User(email='live-check@mivo.invalid', name='Live check', role='buyer', password_hash='x'); db.add(buyer); db.flush()
        products = list(db.scalars(select(Product).where(Product.name == 'Studio ANC Headphones')))
        n = Negotiation(buyer_id=buyer.id, product_id=products[0].id, budget_cents=12500); db.add(n); db.commit()
        nid, ids = n.id, [p.id for p in products]
        floors = {p.id: (p.floor_cents, p.price_cents, db.get(User, p.merchant_id).name) for p in products}
    if engine.dealer_counters is not agents.dealer_counters:
        print('\n(engine not wired to 0G yet in this checkout; using the adapter directly for this run)')
        engine.dealer_counters = agents.dealer_counters
    agents.negotiation_session.set(nid)
    await engine.run_device_negotiation(nid, ids, rounds=2)

    print(f'\n[2] MIVO negotiation {nid}')
    with SessionLocal() as db:
        print('    status', db.get(Negotiation, nid).status)
        for m in db.scalars(select(Message).where(Message.negotiation_id == nid).order_by(Message.sequence)):
            who = floors.get(next((p for p in ids if db.get(Product, p).merchant_id == m.merchant_id), None), ('', '', 'Mivo'))[2] if m.merchant_id else 'Mivo'
            print(f'    [{m.role:8}] {who[:24]:24} {m.text}')
        for o in db.scalars(select(Offer).where(Offer.negotiation_id == nid).order_by(Offer.amount_cents)):
            floor, listing, name = floors[o.product_id]
            assert floor <= o.amount_cents <= listing
            print(f'    offer {o.amount_cents / 100:8.2f} from {name} (listing {listing / 100:.2f}; floor respected)')
        print('    decisions:')
        for d in db.scalars(select(ZeroGDecision).where(ZeroGDecision.negotiation_id == nid).order_by(ZeroGDecision.created)):
            print(f'      round {d.round} {d.role:8} provider={d.provider} request_id={d.request_id} model={d.model} '
                  f'provider_addr={d.provider_address} {d.latency_ms} ms' + (f' FALLBACK: {d.fallback_reason}' if d.fallback_reason else ''))
            print(f'        output {d.model_output}  ->  prices {d.result}')


asyncio.run(main())
