"""Device ingress: a Raspberry Pi POSTs a photo, Gemini + Google Search identifies the product,
and the details come back in the same HTTPS response.

With ?negotiate=true the server also invites demo dealers for that product, runs the normal
AI negotiation on behalf of DEVICE_BUYER_EMAIL, and returns the best offer. The negotiation is
stored like any other, so it shows in that buyer's Deal Room / My Deals on the website, where
the buyer accepts (or not) explicitly.
"""
import asyncio
import hmac
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, or_, func
from backend.config import settings
from backend.db import get_db
from backend.models import Product, User, Negotiation, Offer, now
from backend.agents.gemini import identify_product
from backend.services import dealers
from backend.services.negotiation import run_negotiation, append

router = APIRouter(prefix='/device')
# Vercel caps request bodies at 4.5 MB; stay under it with headroom.
MAX_IMAGE_BYTES = 4 * 1024 * 1024
SIGNATURES = {'image/jpeg': (b'\xff\xd8\xff',), 'image/png': (b'\x89PNG\r\n\x1a\n',), 'image/webp': (b'RIFF',)}


def device_auth(request: Request):
    if not settings.device_api_key: raise HTTPException(503, 'Device access is not configured')
    supplied = request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    if not hmac.compare_digest(supplied.encode(), settings.device_api_key.encode()):
        raise HTTPException(401, 'Invalid device key')


def catalog_matches(db, ident):
    terms = [t for t in (ident.model, ident.brand, ident.name) if t and len(t) >= 3]
    if not terms: return []
    statement = select(Product).where(Product.inventory > 0, Product.listed.is_(True), or_(*[Product.name.ilike(f'%{t[:60]}%') for t in terms])).order_by(Product.price_cents).limit(5)
    return [{'id': p.id, 'name': p.name, 'merchant': db.get(User, p.merchant_id).name, 'price_cents': p.price_cents} for p in db.scalars(statement)]


def device_buyer(db):
    if not settings.device_buyer_email:
        raise HTTPException(503, 'Negotiation needs DEVICE_BUYER_EMAIL set to a buyer account on the server')
    buyer = db.scalar(select(User).where(User.email == settings.device_buyer_email.strip().lower()))
    if not buyer or buyer.role != 'buyer':
        raise HTTPException(503, 'DEVICE_BUYER_EMAIL does not match a buyer account; sign up on the website first')
    return buyer


def public_origin(request):
    host = (request.headers.get('x-forwarded-host') or request.headers.get('host') or '').split(',')[0].strip()
    scheme = 'https' if settings.vercel else request.url.scheme
    return f'{scheme}://{host}' if host else settings.app_origin


def usd(cents): return None if cents is None else round(cents / 100, 2)


async def negotiate(db, request, buyer, ident, budget_usd):
    reference = dealers.reference_cents(ident.price_range_usd)
    if not ident.identified: return {'status': 'skipped', 'reason': 'No product was recognised in the photo'}
    if reference is None: return {'status': 'skipped', 'reason': 'No price estimate was available for this product'}
    products = dealers.create_listings(db, ident, reference, settings.device_dealers)
    budget = round(budget_usd * 100) if budget_usd else round(products[0].price_cents * 0.85)
    n = Negotiation(buyer_id=buyer.id, product_id=products[0].id, budget_cents=budget)
    db.add(n); db.flush()
    append(db, n, 'system', f'Started from a Raspberry Pi photo. Identified: {products[0].name}. '
                            f'{len(products)} demo dealers invited; budget ${budget / 100:,.2f}.')
    db.commit()
    # Runs inside this request (serverless functions freeze after responding). Shielded so a
    # dropped device connection does not abandon the negotiation midway.
    await asyncio.shield(run_negotiation(n.id))
    db.expire_all(); n = db.get(Negotiation, n.id)
    by_id = {p.id: p for p in products}
    offers = []
    for o in db.scalars(select(Offer).where(Offer.negotiation_id == n.id).order_by(Offer.amount_cents)):
        p = by_id.get(o.product_id) or db.get(Product, o.product_id)
        offers.append({'dealer': db.get(User, p.merchant_id).name, 'price_usd': usd(o.amount_cents),
                       'listing_usd': usd(p.price_cents), 'savings_usd': usd(p.price_cents - o.amount_cents),
                       'expires_at': o.expires})
    return {'id': n.id, 'status': n.status, 'budget_usd': usd(budget),
            'dealers': [{'name': db.get(User, p.merchant_id).name, 'listing_usd': usd(p.price_cents)} for p in products],
            'best_offer': offers[0] if offers else None, 'offers': offers,
            'deal_room_url': public_origin(request) + '/deal-room?id=' + n.id}


@router.post('/identify', dependencies=[Depends(device_auth)])
async def identify(request: Request, negotiate_deal: bool = Query(False, alias='negotiate'), budget_usd: float | None = None, db=Depends(get_db)):
    from backend.api.main import rate_limit, expire_stale
    rate_limit(request)
    buyer = None
    if negotiate_deal:
        if budget_usd is not None and not 0.01 <= budget_usd <= 100_000: raise HTTPException(422, 'budget_usd must be between 0.01 and 100000')
        buyer = device_buyer(db)
        expire_stale(db)
        active = db.scalar(select(func.count()).select_from(Negotiation).where(Negotiation.buyer_id == buyer.id, Negotiation.status.in_(['pending', 'running'])))
        if active >= 2: raise HTTPException(429, 'Two negotiations are already running for this buyer; try again shortly')
    mime = request.headers.get('content-type', '').split(';')[0].strip().lower()
    if mime not in SIGNATURES: raise HTTPException(415, 'Send the raw image body as image/jpeg, image/png or image/webp')
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES: raise HTTPException(413, 'Image must be 4 MB or smaller')
    image = bytearray()
    async for chunk in request.stream():
        image += chunk
        if len(image) > MAX_IMAGE_BYTES: raise HTTPException(413, 'Image must be 4 MB or smaller')
    if not image.startswith(SIGNATURES[mime]) or (mime == 'image/webp' and image[8:12] != b'WEBP'):
        raise HTTPException(415, 'Body is not a valid ' + mime)
    if not settings.gemini_api_key: raise HTTPException(503, 'Gemini is not configured')
    try: ident, sources, web_search = await identify_product(bytes(image), mime)
    except Exception: raise HTTPException(502, 'Product identification is unavailable; try again shortly')
    # web_search=false: answered from the model's own knowledge, so prices and retailers may be stale.
    result = {**ident.model_dump(), 'web_search': web_search, 'sources': sources, 'catalog_matches': catalog_matches(db, ident) if ident.identified else []}
    if negotiate_deal: result['negotiation'] = await negotiate(db, request, buyer, ident, budget_usd)
    return result
