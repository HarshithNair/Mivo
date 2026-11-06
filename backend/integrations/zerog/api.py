"""0G endpoints.

Public    GET  /zerog/status                         config + live model availability (no secrets)
Buyer     GET  /negotiations/{nid}/zerog             per-decision provider metadata for your negotiation
Device    GET  /device/zerog/evidence/{nid}          sanitized evidence JSON + content hash (for the uploader)
Device    POST /device/zerog/evidence/{nid}/stored   record a 0G Storage root hash after a verified upload
Buyer     GET  /negotiations/{nid}/zerog/evidence    stored evidence references
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from backend.db import get_db
from backend.models import Negotiation
from backend.services.auth import current_user
from backend.api.device import device_auth
from backend.integrations.zerog import compute, evidence
from backend.integrations.zerog.config import zerog_settings as zs
from backend.integrations.zerog.models import ZeroGDecision, ZeroGEvidence

router = APIRouter()


def owned(db, nid, user):
    n = db.get(Negotiation, nid)
    if not n or n.buyer_id != user.id: raise HTTPException(404, 'Negotiation not found')
    return n


@router.get('/zerog/status')
async def status():
    body = {'enabled': zs.active, 'router': zs.zerog_router_url, 'model': zs.zerog_model, 'fallback': 'gemini'}
    try: body['model_listed'] = any(m.get('id') == zs.zerog_model for m in await compute.list_models())
    except Exception as exc: body['model_listed'], body['router_error'] = None, type(exc).__name__
    return body


@router.get('/negotiations/{nid}/zerog')
def decisions(nid: str, user=Depends(current_user), db=Depends(get_db)):
    owned(db, nid, user)
    rows = db.scalars(select(ZeroGDecision).where(ZeroGDecision.negotiation_id == nid).order_by(ZeroGDecision.created))
    return [{'role': d.role, 'round': d.round, 'provider': d.provider, 'model': d.model, 'request_id': d.request_id,
             'provider_address': d.provider_address, 'tee_verified': d.tee_verified, 'latency_ms': d.latency_ms,
             'attempts': d.attempts, 'fallback_reason': d.fallback_reason, 'created': d.created} for d in rows]


@router.get('/negotiations/{nid}/zerog/evidence')
def evidence_refs(nid: str, user=Depends(current_user), db=Depends(get_db)):
    owned(db, nid, user)
    return [{'content_hash': e.content_hash, 'root_hash': e.root_hash, 'tx_hash': e.tx_hash, 'verified': e.verified, 'created': e.created}
            for e in db.scalars(select(ZeroGEvidence).where(ZeroGEvidence.negotiation_id == nid).order_by(ZeroGEvidence.created))]


@router.get('/device/zerog/evidence/{nid}', dependencies=[Depends(device_auth)])
def device_evidence(nid: str, db=Depends(get_db)):
    doc = evidence.build(db, nid)
    if not doc: raise HTTPException(404, 'Negotiation not found')
    # canonical = the exact bytes to store; sha256(canonical) == content_hash
    return {'evidence': doc, 'content_hash': evidence.content_hash(doc), 'canonical': evidence.canonical(doc).decode()}


class Stored(BaseModel):
    content_hash: str = Field(pattern=r'^0x[0-9a-f]{64}$')
    root_hash: str = Field(pattern=r'^0x[0-9a-fA-F]{64}$')
    tx_hash: str | None = Field(default=None, pattern=r'^0x[0-9a-fA-F]{64}$')
    verified: bool


@router.post('/device/zerog/evidence/{nid}/stored', dependencies=[Depends(device_auth)])
def device_stored(nid: str, body: Stored, db=Depends(get_db)):
    if not body.verified: raise HTTPException(422, 'Only record evidence after download + Merkle proof + hash verification')
    doc = evidence.build(db, nid)
    if not doc: raise HTTPException(404, 'Negotiation not found')
    if evidence.content_hash(doc) != body.content_hash: raise HTTPException(409, 'Evidence changed since upload; upload again')
    e = ZeroGEvidence(negotiation_id=nid, content_hash=body.content_hash, root_hash=body.root_hash.lower(),
                      tx_hash=body.tx_hash.lower() if body.tx_hash else None, verified=True)
    db.add(e)
    try: db.commit()
    except IntegrityError: db.rollback()  # same root already recorded
    return {'ok': True, 'root_hash': body.root_hash.lower()}
