import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import select, or_, update, func
from sqlalchemy.exc import IntegrityError
from backend.config import settings
from backend.db import get_db, SessionLocal
from backend.models import User, Session, Product, Negotiation, Message, Offer, Quote, SavedProduct, Audit, now
from backend.schemas import Registration, Credentials, ProductInput, StartNegotiation, SearchRequest
from backend.services.auth import current_user, merchant, passwords, DUMMY_HASH, token_hash
from backend.services.negotiation import run_negotiation
from backend.agents.gemini import search_intent
from backend.api.payments import router as payments_router
from backend.api.world import router as world_router
from backend.api.device import router as device_router
from backend.services.payments import enabled as payment_enabled

log=logging.getLogger('mivo.api')
tasks=set()
def expire_stale(db):
    cutoff=now()-settings.negotiation_deadline-60
    db.execute(update(Negotiation).where(Negotiation.status.in_(['running','pending']),Negotiation.created<cutoff).values(status='failed')); db.commit()
@asynccontextmanager
async def lifespan(app):
    # Interrupted jobs fail visibly; never manufacture offers after restart.
    # On serverless, other instances may be mid-negotiation, so only fail stale jobs.
    try:
        with SessionLocal() as db:
            if settings.vercel: expire_stale(db)
            else: db.execute(update(Negotiation).where(Negotiation.status.in_(['running','pending'])).values(status='failed')); db.commit()
    except Exception:
        # Keep serving so /health can report the problem instead of every request crashing.
        log.exception('startup database cleanup failed')
    yield
    for task in tasks: task.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
app=FastAPI(title='Mivo API',version='0.1.0',lifespan=lifespan)
app.include_router(payments_router)
app.include_router(world_router)
app.include_router(device_router)

def origin_allowed(headers):
    origin=headers.get('origin')
    if origin in settings.allowed_origins: return True
    # On Vercel the frontend and API share one domain, and a project answers on several
    # (production alias, team alias, custom domains). Same-origin means the browser's Origin
    # matches the host the request arrived on; the edge sets that host, not the page.
    host=headers.get('x-forwarded-host') or headers.get('host')
    return settings.vercel and bool(origin and host) and origin=='https://'+host.split(',')[0].strip()
@app.middleware('http')
async def guard(request, call_next):
    # /device/* is called by hardware, not browsers: no cookies are used there, so it is
    # authenticated by a bearer key instead of the browser Origin check.
    if request.method not in ('GET','HEAD','OPTIONS') and not request.url.path.startswith('/device/') and not origin_allowed(request.headers):
        return Response('Invalid request origin',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    return response

# Single-process local rate limiter. Production must use a shared gateway/Redis limiter.
attempts={}
def rate_limit(request):
    key=request.client.host if request.client else 'unknown'; t=time.monotonic()
    times=[x for x in attempts.get(key,[]) if t-x<60]
    if len(times)>=20: raise HTTPException(429,'Too many attempts; try again shortly')
    attempts[key]=times+[t]

def public_user(user): return {'id':user.id,'name':user.name,'email':user.email,'role':user.role}
def product_data(p,db,private=False):
    data={k:getattr(p,k) for k in ['id','name','category','description','price_cents','inventory','image','merchant_id']}
    data['merchant']=db.get(User,p.merchant_id).name
    if private: data['floor_cents']=p.floor_cents
    return data

def issue_session(user,db,response):
    token=secrets.token_urlsafe(32)
    db.add(Session(token_hash=token_hash(token),user_id=user.id,expires=now()+604800)); db.commit()
    response.set_cookie('mivo_session',token,httponly=True,secure=settings.cookie_secure,samesite='strict',max_age=604800,path='/')
    return public_user(user)

@app.get('/health')
def health(response:Response,db=Depends(get_db)):
    body={'status':'ok','database':db.get_bind().dialect.name,'gemini_configured':bool(settings.gemini_api_key),'device_configured':bool(settings.device_api_key),'settlement_enabled':payment_enabled()}
    try:
        db.execute(select(1)); body['seeded_products']=db.scalar(select(func.count()).select_from(Product))
    except Exception as exc:
        # Report only the error class: messages can contain connection strings.
        db.rollback(); log.exception('health check failed'); response.status_code=503
        body.update(status='error',error=type(exc).__name__)
    return body
@app.post('/auth/register',status_code=201)
def register(body:Registration,request:Request,response:Response,db=Depends(get_db)):
    rate_limit(request)
    user=User(email=body.email.lower(),name=body.name,role=body.role,password_hash=passwords.hash(body.password))
    db.add(user)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,'Account cannot be created with that email')
    return issue_session(user,db,response)
@app.post('/auth/login')
def login(body:Credentials,request:Request,response:Response,db=Depends(get_db)):
    rate_limit(request)
    user=db.scalar(select(User).where(User.email==body.email.lower()))
    valid=passwords.verify(body.password,user.password_hash if user else DUMMY_HASH)
    if not user or not valid: raise HTTPException(401,'Invalid email or password')
    return issue_session(user,db,response)
@app.post('/auth/logout')
def logout(request:Request,response:Response,db=Depends(get_db)):
    session=db.get(Session,token_hash(request.cookies.get('mivo_session','')))
    if session: db.delete(session); db.commit()
    response.delete_cookie('mivo_session',path='/'); return {'ok':True}
@app.get('/auth/me')
def me(user=Depends(current_user)): return public_user(user)

@app.get('/products')
def products(q:str='',category:str='',max_price:int|None=None,db=Depends(get_db)):
    statement=select(Product).where(Product.inventory>0,Product.listed.is_(True))
    if q: statement=statement.where(or_(Product.name.ilike(f'%{q[:100]}%'),Product.description.ilike(f'%{q[:100]}%')))
    if category: statement=statement.where(Product.category==category)
    if max_price is not None: statement=statement.where(Product.price_cents<=max_price)
    return [product_data(p,db) for p in db.scalars(statement.order_by(Product.price_cents).limit(100))]
@app.post('/search')
async def search(body:SearchRequest,request:Request,db=Depends(get_db),user=Depends(current_user)):
    rate_limit(request)
    if not settings.gemini_api_key: raise HTTPException(503,'AI search requires Gemini configuration. Catalog search remains available.')
    try: intent=await search_intent(body.query)
    except Exception: raise HTTPException(502,'AI search unavailable; try catalog search')
    statement=select(Product).where(Product.inventory>0,Product.listed.is_(True))
    if intent.category: statement=statement.where(Product.category==intent.category)
    if intent.budget_cents: statement=statement.where(Product.price_cents<=intent.budget_cents)
    for term in intent.brands+intent.features:
        statement=statement.where(or_(Product.name.ilike(f'%{term}%'),Product.description.ilike(f'%{term}%')))
    if not intent.category:
        for term in intent.keywords: statement=statement.where(or_(Product.name.ilike(f'%{term}%'),Product.description.ilike(f'%{term}%')))
    return {'intent':intent.model_dump(),'products':[product_data(p,db) for p in db.scalars(statement.limit(100))]}
@app.get('/merchant/products')
def merchant_products(user=Depends(merchant),db=Depends(get_db)):
    return [product_data(p,db,True) for p in db.scalars(select(Product).where(Product.merchant_id==user.id))]
@app.post('/merchant/products',status_code=201)
def add_product(body:ProductInput,user=Depends(merchant),db=Depends(get_db)):
    p=Product(**body.model_dump(),merchant_id=user.id); db.add(p); db.commit(); return product_data(p,db,True)
@app.put('/merchant/products/{pid}')
def edit_product(pid:str,body:ProductInput,user=Depends(merchant),db=Depends(get_db)):
    p=db.get(Product,pid)
    if not p or p.merchant_id!=user.id: raise HTTPException(404,'Product not found')
    for k,v in body.model_dump().items(): setattr(p,k,v)
    db.commit(); return product_data(p,db,True)
@app.delete('/merchant/products/{pid}')
def delete_product(pid:str,user=Depends(merchant),db=Depends(get_db)):
    p=db.get(Product,pid)
    if not p or p.merchant_id!=user.id: raise HTTPException(404,'Product not found')
    p.inventory=0; db.commit(); return {'ok':True}
@app.get('/saved')
def saved(user=Depends(current_user),db=Depends(get_db)):
    return [product_data(p,db) for p in db.scalars(select(Product).join(SavedProduct).where(SavedProduct.user_id==user.id))]
@app.post('/saved/{pid}')
def save(pid:str,user=Depends(current_user),db=Depends(get_db)):
    if not db.get(Product,pid): raise HTTPException(404,'Product not found')
    item=db.get(SavedProduct,(user.id,pid))
    if item: db.delete(item)
    else: db.add(SavedProduct(user_id=user.id,product_id=pid))
    db.commit(); return {'saved':not bool(item)}

def negotiation_data(n,db):
    return {'id':n.id,'status':n.status,'budget_cents':n.budget_cents,'product':product_data(db.get(Product,n.product_id),db),'messages':[{'id':m.id,'sequence':m.sequence,'role':m.role,'text':m.text,'amount_cents':m.amount_cents,'merchant':db.get(User,m.merchant_id).name if m.merchant_id else 'Mivo','created':m.created} for m in db.scalars(select(Message).where(Message.negotiation_id==n.id).order_by(Message.sequence))],'offers':[{'id':o.id,'amount_cents':o.amount_cents,'expires':o.expires,'product':product_data(db.get(Product,o.product_id),db)} for o in db.scalars(select(Offer).where(Offer.negotiation_id==n.id).order_by(Offer.amount_cents))]}
@app.post('/negotiations',status_code=201)
async def start(body:StartNegotiation,request:Request,user=Depends(current_user),db=Depends(get_db)):
    rate_limit(request)
    if user.role!='buyer': raise HTTPException(403,'Buyer account required')
    if not settings.gemini_api_key: raise HTTPException(503,'Connect Gemini to start real AI negotiations.')
    product=db.get(Product,body.product_id)
    if not product or product.inventory<1: raise HTTPException(404,'Product unavailable')
    expire_stale(db)
    active=db.scalar(select(func.count()).select_from(Negotiation).where(Negotiation.buyer_id==user.id,Negotiation.status.in_(['pending','running'])))
    if active>=2: raise HTTPException(429,'Finish or cancel an active negotiation first')
    n=Negotiation(buyer_id=user.id,product_id=product.id,budget_cents=body.budget_cents); db.add(n); db.commit()
    if settings.vercel:
        # Serverless functions freeze after responding, so the client drives the run via /run.
        return {'id':n.id,'run':True}
    task=asyncio.create_task(run_negotiation(n.id)); tasks.add(task); task.add_done_callback(tasks.discard)
    return {'id':n.id,'run':False}
@app.post('/negotiations/{nid}/run')
async def run(nid:str,user=Depends(current_user),db=Depends(get_db)):
    n=db.get(Negotiation,nid)
    if not n or n.buyer_id!=user.id: raise HTTPException(404,'Negotiation not found')
    # run_negotiation atomically claims pending jobs, so repeated calls are harmless.
    # Shield it so a dropped client connection does not abandon a negotiation mid-round.
    await asyncio.shield(run_negotiation(nid))
    db.expire_all(); return {'status':db.get(Negotiation,nid).status}
@app.get('/negotiations')
def negotiations(user=Depends(current_user),db=Depends(get_db)):
    return [negotiation_data(n,db) for n in db.scalars(select(Negotiation).where(Negotiation.buyer_id==user.id).order_by(Negotiation.created.desc()).limit(50))]
@app.get('/negotiations/{nid}')
def negotiation(nid:str,user=Depends(current_user),db=Depends(get_db)):
    expire_stale(db)
    n=db.get(Negotiation,nid)
    if not n or n.buyer_id!=user.id: raise HTTPException(404,'Negotiation not found')
    return negotiation_data(n,db)
@app.post('/negotiations/{nid}/cancel')
def cancel(nid:str,user=Depends(current_user),db=Depends(get_db)):
    result=db.execute(update(Negotiation).where(Negotiation.id==nid,Negotiation.buyer_id==user.id,Negotiation.status.in_(['pending','running'])).values(status='cancelled'))
    db.commit()
    if result.rowcount!=1: raise HTTPException(409,'Negotiation cannot be cancelled')
    return {'ok':True}
@app.post('/offers/{oid}/accept')
def accept(oid:str,user=Depends(current_user),db=Depends(get_db)):
    o=db.get(Offer,oid)
    n=db.get(Negotiation,o.negotiation_id) if o else None
    if not n or n.buyer_id!=user.id: raise HTTPException(404,'Offer not found')
    existing=db.scalar(select(Quote).where(Quote.negotiation_id==n.id))
    if existing:
        if existing.offer_id!=oid: raise HTTPException(409,'Another offer was accepted')
        return {'id':existing.id}
    p=db.get(Product,o.product_id)
    if n.status!='completed' or o.expires<=now() or p.inventory<1 or o.amount_cents<p.floor_cents: raise HTTPException(409,'Offer no longer valid')
    result=db.execute(update(Negotiation).where(Negotiation.id==n.id,Negotiation.status=='completed').values(status='accepted'))
    if result.rowcount!=1: db.rollback(); raise HTTPException(409,'Offer already accepted')
    quote=Quote(negotiation_id=n.id,offer_id=o.id,buyer_id=user.id,amount_cents=o.amount_cents,expires=o.expires)
    db.add(quote); db.add(Audit(actor=user.id,action='accept',reference=o.id)); db.commit(); return {'id':quote.id}
@app.get('/quotes/{qid}')
def quote(qid:str,user=Depends(current_user),db=Depends(get_db)):
    q=db.get(Quote,qid)
    if not q or q.buyer_id!=user.id: raise HTTPException(404,'Quote not found')
    o=db.get(Offer,q.offer_id)
    return {'id':q.id,'amount_cents':q.amount_cents,'expires':q.expires,'status':'expired' if q.expires<=now() and q.status!='paid' else q.status,'product':product_data(db.get(Product,o.product_id),db),'payment_enabled':payment_enabled()}
@app.websocket('/ws/negotiations/{nid}')
async def live(ws:WebSocket,nid:str):
    if not origin_allowed(ws.headers): await ws.close(code=1008); return
    with SessionLocal() as db:
        s=db.get(Session,token_hash(ws.cookies.get('mivo_session','')))
        n=db.get(Negotiation,nid)
        if not s or s.expires<=now() or not n or n.buyer_id!=s.user_id: await ws.close(code=1008); return
    await ws.accept()
    try:
        while True:
            with SessionLocal() as db:
                s=db.get(Session,token_hash(ws.cookies.get('mivo_session','')))
                if not s or s.expires<=now(): await ws.close(code=1008); return
                n=db.get(Negotiation,nid); data=negotiation_data(n,db)
            await ws.send_json(data)
            if data['status'] not in ['pending','running']: await ws.close(); return
            await asyncio.sleep(1)
    except WebSocketDisconnect: pass
