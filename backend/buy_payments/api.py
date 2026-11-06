"""HTTP surface for device BUY payments.

Device (Raspberry Pi, bearer device key; paths under /device/ like identify):
    POST /device/buy                     BUY signal -> pending payment (BUY_API.md)
    GET  /device/payments/{payment_id}   status for the Pi, verified against the chain
Website (logged-in buyer session):
    GET  /buy-payments                   recent payments for the portal
    GET  /buy-payments/{id}              one payment, refreshed from the chain
    POST /buy-payments/{id}/start        buyer is about to approve in MetaMask
    POST /buy-payments/{id}/submit       MetaMask returned a transaction hash
    POST /buy-payments/{id}/report       wallet rejection / not enough gas
"""
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from backend.db import get_db
from backend.services.auth import current_user
from backend.api.device import device_auth, device_buyer
from backend.buy_payments import service
from backend.buy_payments.models import BuyPayment

router = APIRouter()


class BuySignal(BaseModel):
    command: Literal['buy'] = 'buy'
    request_id: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9._:-]+$')
    negotiation_id: str = Field(min_length=1, max_length=64)
    offer_id: str | None = Field(default=None, max_length=64)  # accepted for forward compatibility; best offer is used
    dealer: str | None = Field(default=None, max_length=120)
    price_usd: float | None = Field(default=None, gt=0, le=100_000)
    deal_room_url: str | None = Field(default=None, max_length=500)


class StartInput(BaseModel): payer_address: str = Field(pattern=r'^0x[0-9a-fA-F]{40}$')
class SubmitInput(BaseModel): tx_hash: str = Field(pattern=r'^0x[0-9a-fA-F]{64}$')
class ReportInput(BaseModel):
    kind: Literal['rejected', 'insufficient_gas']
    detail: str | None = Field(default=None, max_length=200)


@router.post('/device/buy', dependencies=[Depends(device_auth)])
def device_buy(body: BuySignal, request: Request, db=Depends(get_db)):
    from backend.api.main import rate_limit
    rate_limit(request)
    p = service.create_from_buy(db, device_buyer(db), body)
    return {**service.device_view(p), 'message': 'Payment request created. Approve it in MetaMask on the Mivo Payments page.'
            if p.status == 'pending' else service.device_view(p)['message']}


@router.get('/device/payments/{payment_id}', dependencies=[Depends(device_auth)])
async def device_payment(payment_id: str, db=Depends(get_db)):
    buyer = device_buyer(db)
    p = service.owned(db, payment_id, buyer)
    return service.device_view(await service.refresh(db, p))


@router.get('/buy-payments')
async def list_payments(user=Depends(current_user), db=Depends(get_db)):
    payments = list(db.scalars(select(BuyPayment).where(BuyPayment.buyer_id == user.id).order_by(BuyPayment.created.desc()).limit(20)))
    for p in payments[:3]: await service.refresh(db, p)  # keep the newest ones live; the rest are final
    return [service.portal_view(p) for p in payments]


@router.get('/buy-payments/{payment_id}')
async def get_payment(payment_id: str, user=Depends(current_user), db=Depends(get_db)):
    return service.portal_view(await service.refresh(db, service.owned(db, payment_id, user)))


@router.post('/buy-payments/{payment_id}/start')
async def start_payment(payment_id: str, body: StartInput, user=Depends(current_user), db=Depends(get_db)):
    return service.portal_view(await service.start(db, service.owned(db, payment_id, user), body.payer_address))


@router.post('/buy-payments/{payment_id}/submit')
async def submit_payment(payment_id: str, body: SubmitInput, user=Depends(current_user), db=Depends(get_db)):
    return service.portal_view(await service.submit(db, service.owned(db, payment_id, user), body.tx_hash))


@router.post('/buy-payments/{payment_id}/report')
def report_payment(payment_id: str, body: ReportInput, user=Depends(current_user), db=Depends(get_db)):
    return service.portal_view(service.report(db, service.owned(db, payment_id, user), body.kind, body.detail))
