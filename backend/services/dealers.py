"""Demo dealers for negotiations started from a device scan.

Prices come from Gemini's estimate of the scanned product, which is untrusted model
output, so everything is clamped. Each dealer gets a listing a little around that
estimate and a private floor below it; the existing negotiation engine then enforces
floor <= offer <= listing exactly as for real merchants.
"""
import random
import secrets
from pwdlib import PasswordHash
from sqlalchemy import select, update
from backend.models import User, Product

DEALER_NAMES = [
    'Metro Mobiles', 'QuickTech Traders', 'Urban Gadget Hub', 'Prime Electronics',
    'ValueCell Outlet', 'Circuit Corner', 'BrightBuy Store', 'NextGen Deals',
]
SUFFIX = ' · Demo'  # demo merchants are always labelled as such
MIN_CENTS, MAX_CENTS = 100, 5_000_000  # $1 .. $50,000
IMAGE = '/scan.svg'


def reference_cents(price_range):
    """Midpoint of the model's USD estimate, in cents, or None if it gave no usable price."""
    if price_range is None: return None
    values = [v for v in (price_range.low, price_range.high) if isinstance(v, (int, float)) and v > 0]
    if not values: return None
    cents = round(sum(values) / len(values) * 100)
    return min(max(cents, MIN_CENTS), MAX_CENTS)


def dealer_accounts(db, count, rng):
    """Persistent demo dealer users (random, unusable passwords), created on first use."""
    names = rng.sample(DEALER_NAMES, k=min(count, len(DEALER_NAMES)))
    accounts = []
    for name in names:
        slug = name.lower().replace(' ', '-')
        email = f'dealer-{slug}@mivo.invalid'
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, name=name + SUFFIX, role='merchant',
                        password_hash=PasswordHash.recommended().hash(secrets.token_urlsafe(40)))
            db.add(user); db.flush()
        accounts.append(user)
    return accounts


def create_listings(db, ident, reference, count, rng=None):
    """Create unlisted products for `count` demo dealers. Returns them cheapest-listing first."""
    rng = rng or random.Random()
    name = (ident.name or ident.model or 'Scanned product')[:120]
    # Retire earlier scan listings of the same name so this negotiation only meets this scan's dealers.
    db.execute(update(Product).where(Product.name == name, Product.listed.is_(False)).values(inventory=0))
    products = []
    for dealer in dealer_accounts(db, count, rng):
        listing = min(max(round(reference * rng.uniform(0.97, 1.10)), MIN_CENTS), MAX_CENTS)
        floor = max(round(listing * rng.uniform(0.80, 0.92)), 1)
        product = Product(merchant_id=dealer.id, name=name, category=(ident.category or 'Scanned')[:40],
                          description=(ident.description or 'Identified from a device photo.')[:600],
                          price_cents=listing, floor_cents=floor, inventory=rng.randint(1, 8),
                          image=IMAGE, listed=False)
        db.add(product); products.append(product)
    db.flush()
    return sorted(products, key=lambda p: p.price_cents)
