import asyncio
import logging
from sqlalchemy import select, update, func
from backend.db import SessionLocal
from backend.models import Negotiation, Product, Message, Offer, Audit, now
from backend.agents.gemini import buyer_proposal, merchant_proposal
from backend.config import settings

MAX_ROUNDS = settings.negotiation_rounds
log = logging.getLogger('mivo.negotiation')

def validate_price(amount, lower, upper):
    if type(amount) is not int or not lower <= amount <= upper:
        raise ValueError('Agent proposal outside authorized bounds')
    return amount

def append(db, n, role, text, amount=None, merchant=None):
    sequence = (db.scalar(select(func.max(Message.sequence)).where(Message.negotiation_id==n.id)) or 0)+1
    db.add(Message(negotiation_id=n.id,sequence=sequence,role=role,text=text,amount_cents=amount,merchant_id=merchant))

async def run_negotiation(nid):
    with SessionLocal() as db:
        claimed = db.execute(update(Negotiation).where(Negotiation.id==nid, Negotiation.status=='pending').values(status='running'))
        db.commit()
        if claimed.rowcount != 1: return
        n = db.get(Negotiation,nid)
        original = db.get(Product,n.product_id)
        products = list(db.scalars(select(Product).where(Product.name==original.name,Product.inventory>0)))[:5]
        history=[]
        try:
            for round_no in range(1,MAX_ROUNDS+1):
                db.refresh(n)
                if n.status != 'running': return
                if now()-n.created > settings.negotiation_deadline: raise TimeoutError()
                buyer=await buyer_proposal({'budget_cents':n.budget_cents,'listing_cents':original.price_cents,'round':round_no,'history':history})
                amount=validate_price(buyer.amount_cents,1,n.budget_cents)
                db.refresh(n)
                if n.status != 'running': return
                append(db,n,'buyer',f'Round {round_no}: proposing ${amount/100:.2f}.',amount)
                db.commit()
                async def respond(p):
                    proposal=await merchant_proposal({'buyer_offer_cents':amount,'listing_cents':p.price_cents,'private_floor_cents':p.floor_cents,'inventory':p.inventory,'round':round_no,'history':[h for h in history if h['merchant_id']==p.merchant_id]})
                    return p,validate_price(proposal.amount_cents,p.floor_cents,p.price_cents)
                results=await asyncio.gather(*(respond(p) for p in products),return_exceptions=True)
                db.refresh(n)
                if n.status != 'running': return
                for result in results:
                    if isinstance(result,BaseException): continue
                    p,price=result
                    append(db,n,'merchant',f'Merchant counteroffer: ${price/100:.2f}.',price,p.merchant_id)
                    history.append({'merchant_id':p.merchant_id,'amount_cents':price,'round':round_no})
                    if round_no==MAX_ROUNDS:
                        db.add(Offer(negotiation_id=n.id,product_id=p.id,amount_cents=price,expires=now()+600))
                db.commit()
            offers=list(db.scalars(select(Offer).where(Offer.negotiation_id==nid)))
            n.status='completed' if offers else 'failed'
            append(db,n,'system','Offers are ready for your review. Choose explicitly to accept.' if offers else 'No valid merchant offers were received.')
            db.add(Audit(actor=n.buyer_id,action=n.status,reference=n.id)); db.commit()
        except Exception:
            log.exception('negotiation %s failed', nid)
            db.rollback(); db.refresh(n)
            if n.status=='running':
                n.status='failed'; append(db,n,'system','Negotiation could not complete. Please retry; no deal was accepted.'); db.commit()
