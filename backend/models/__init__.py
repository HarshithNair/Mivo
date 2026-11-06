import time
import uuid
from sqlalchemy import ForeignKey, String, Integer, Text, UniqueConstraint, Boolean, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def uid(): return str(uuid.uuid4())
def now(): return int(time.time())

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))

class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires: Mapped[int] = mapped_column(Integer)

class Product(Base):
    __tablename__ = 'products'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    floor_cents: Mapped[int] = mapped_column(Integer)
    inventory: Mapped[int] = mapped_column(Integer, default=10)
    image: Mapped[str] = mapped_column(String(100), default='/headphones.svg')
    # False for demo-dealer listings generated from device scans: negotiable, but kept out of the catalog.
    listed: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

class Negotiation(Base):
    __tablename__ = 'negotiations'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    buyer_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    budget_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(default='pending')
    created: Mapped[int] = mapped_column(default=now)

class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (UniqueConstraint('negotiation_id', 'sequence'),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    negotiation_id: Mapped[str] = mapped_column(ForeignKey('negotiations.id'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))
    merchant_id: Mapped[str | None] = mapped_column(nullable=True)
    text: Mapped[str] = mapped_column(Text)
    amount_cents: Mapped[int | None] = mapped_column(nullable=True)
    created: Mapped[int] = mapped_column(default=now)

class Offer(Base):
    __tablename__ = 'offers'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    negotiation_id: Mapped[str] = mapped_column(ForeignKey('negotiations.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    amount_cents: Mapped[int] = mapped_column(Integer)
    expires: Mapped[int] = mapped_column(Integer)

class Quote(Base):
    __tablename__ = 'quotes'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    negotiation_id: Mapped[str] = mapped_column(ForeignKey('negotiations.id'), unique=True)
    offer_id: Mapped[str] = mapped_column(ForeignKey('offers.id'), unique=True)
    buyer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    amount_cents: Mapped[int] = mapped_column(Integer)
    expires: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(default='accepted')

class SavedProduct(Base):
    __tablename__ = 'saved_products'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), primary_key=True)

class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    reference: Mapped[str] = mapped_column(String(80))
    created: Mapped[int] = mapped_column(default=now)

class WalletChallenge(Base):
    __tablename__ = 'wallet_challenges'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    address: Mapped[str] = mapped_column(String(42))
    message: Mapped[str] = mapped_column(Text)
    expires: Mapped[int] = mapped_column(Integer)
    used: Mapped[bool] = mapped_column(default=False)

class WalletConnection(Base):
    __tablename__ = 'wallet_connections'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    address: Mapped[str] = mapped_column(String(42), unique=True)
    verified: Mapped[int] = mapped_column(default=now)

class CheckoutIntent(Base):
    __tablename__ = 'checkout_intents'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    quote_id: Mapped[str] = mapped_column(ForeignKey('quotes.id'), unique=True)
    buyer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    merchant_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    buyer_address: Mapped[str] = mapped_column(String(42))
    merchant_address: Mapped[str] = mapped_column(String(42))
    chain_id: Mapped[int] = mapped_column(Integer)
    contract_address: Mapped[str] = mapped_column(String(42))
    token_address: Mapped[str] = mapped_column(String(42))
    token_amount: Mapped[str] = mapped_column(String(80))
    nonce: Mapped[str] = mapped_column(String(80))
    expires: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str] = mapped_column(Text)
    quote_hash: Mapped[str] = mapped_column(String(66),unique=True)
    status: Mapped[str] = mapped_column(default='pending')

class Payment(Base):
    __tablename__ = 'payments'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    intent_id: Mapped[str] = mapped_column(ForeignKey('checkout_intents.id'),unique=True)
    transaction_hash: Mapped[str] = mapped_column(String(66),unique=True)
    block_number: Mapped[int] = mapped_column(Integer)
    block_hash: Mapped[str] = mapped_column(String(66))
    confirmed: Mapped[int] = mapped_column(default=now)

class Order(Base):
    __tablename__ = 'orders'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    payment_id: Mapped[str] = mapped_column(ForeignKey('payments.id'),unique=True)
    buyer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    merchant_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    amount_cents: Mapped[int] = mapped_column(Integer)
    created: Mapped[int] = mapped_column(default=now)

class WorldAttempt(Base):
    __tablename__ = 'world_attempts'
    state_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    nonce: Mapped[str] = mapped_column(String(100))
    verifier: Mapped[str] = mapped_column(String(128))
    expires: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(default='pending')

class WorldVerification(Base):
    __tablename__ = 'world_verifications'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'),primary_key=True)
    subject_hash: Mapped[str] = mapped_column(String(64),unique=True)
    auth_time: Mapped[int] = mapped_column(Integer)
    expires: Mapped[int] = mapped_column(Integer)
    assurance: Mapped[str] = mapped_column(String(100))
    sandbox: Mapped[bool] = mapped_column(default=True)
