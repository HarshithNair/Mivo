from sqlalchemy import ForeignKey, String, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.models import Base, uid, now

# Lifecycle. Final states are what the Pi treats as finished (BUY_API.md).
PENDING, AWAITING, SUBMITTED, CONFIRMING = 'pending', 'awaiting_approval', 'submitted', 'confirming'
PAID, FAILED, EXPIRED, REJECTED = 'paid', 'failed', 'expired', 'rejected'
ACTIVE = (PENDING, AWAITING, SUBMITTED, CONFIRMING)
FINAL = (PAID, FAILED, EXPIRED, REJECTED)


class BuyPayment(Base):
    __tablename__ = 'buy_payments'
    __table_args__ = (UniqueConstraint('negotiation_id', 'attempt'),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: 'PAY_' + uid().replace('-', '')[:20].upper())
    request_id: Mapped[str] = mapped_column(String(80), unique=True)
    negotiation_id: Mapped[str] = mapped_column(ForeignKey('negotiations.id'), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    offer_id: Mapped[str] = mapped_column(ForeignKey('offers.id'))
    quote_id: Mapped[str] = mapped_column(ForeignKey('quotes.id'))
    buyer_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    product_name: Mapped[str] = mapped_column(String(120))
    dealer: Mapped[str] = mapped_column(String(120))
    amount_cents: Mapped[int] = mapped_column(Integer)
    token_amount: Mapped[str] = mapped_column(String(40))  # integer string in token base units (6 decimals)
    token_address: Mapped[str] = mapped_column(String(42))
    recipient_address: Mapped[str] = mapped_column(String(42))
    chain_id: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(String(66))  # 0x + 32 bytes appended to the transfer calldata
    status: Mapped[str] = mapped_column(String(24), default=PENDING, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    events: Mapped[str] = mapped_column(Text, default='[]')  # JSON timeline for the portal
    payer_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    start_block: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), unique=True, nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created: Mapped[int] = mapped_column(Integer, default=now)
    expires: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked: Mapped[int] = mapped_column(Integer, default=0)
