from sqlalchemy import ForeignKey, String, Integer, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from backend.models import Base, uid, now


class ZeroGDecision(Base):
    """One AI decision in a negotiation: which provider made it and the 0G request that proves it."""
    __tablename__ = 'zerog_decisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    negotiation_id: Mapped[str | None] = mapped_column(ForeignKey('negotiations.id'), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(16))           # buyer | merchant | dealers
    round: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(16))       # 0g | gemini
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider_address: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_identity: Mapped[str | None] = mapped_column(Text, nullable=True)
    tee_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    model_output: Mapped[str | None] = mapped_column(Text, nullable=True)   # validated JSON the model returned
    result: Mapped[str | None] = mapped_column(Text, nullable=True)         # prices the server derived (JSON)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created: Mapped[int] = mapped_column(Integer, default=now)


class ZeroGEvidence(Base):
    """A sanitized negotiation record stored on 0G Storage."""
    __tablename__ = 'zerog_evidence'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    negotiation_id: Mapped[str] = mapped_column(ForeignKey('negotiations.id'), index=True)
    content_hash: Mapped[str] = mapped_column(String(66))   # sha256 of the canonical JSON
    root_hash: Mapped[str] = mapped_column(String(66), unique=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # downloaded with Merkle proof + hash match
    created: Mapped[int] = mapped_column(Integer, default=now)
