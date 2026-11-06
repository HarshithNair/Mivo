"""Device ingress: a Raspberry Pi POSTs a photo, Gemini + Google Search identifies the product,
and the details come back in the same HTTPS response."""
import hmac
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, or_
from backend.config import settings
from backend.db import get_db
from backend.models import Product, User
from backend.agents.gemini import identify_product

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
    statement = select(Product).where(Product.inventory > 0, or_(*[Product.name.ilike(f'%{t[:60]}%') for t in terms])).order_by(Product.price_cents).limit(5)
    return [{'id': p.id, 'name': p.name, 'merchant': db.get(User, p.merchant_id).name, 'price_cents': p.price_cents} for p in db.scalars(statement)]


@router.post('/identify', dependencies=[Depends(device_auth)])
async def identify(request: Request, db=Depends(get_db)):
    from backend.api.main import rate_limit
    rate_limit(request)
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
    return {**ident.model_dump(), 'web_search': web_search, 'sources': sources, 'catalog_matches': catalog_matches(db, ident) if ident.identified else []}
