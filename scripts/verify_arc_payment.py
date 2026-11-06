#!/usr/bin/env python3
"""Independently verify a Mivo USDC payment on Arc Testnet from the command line.

    .venv/bin/python scripts/verify_arc_payment.py PAY_XXXX            # a payment in the DB (uses DATABASE_URL)
    .venv/bin/python scripts/verify_arc_payment.py --tx 0xHASH --from 0xPAYER --to 0xRECIPIENT --amount-units N [--reference 0x…]

Uses exactly the same checks the backend uses before marking a payment successful.
"""
import argparse
import asyncio
import sys
from types import SimpleNamespace

sys.path.insert(0, __file__.rsplit('/scripts/', 1)[0])
from backend.buy_payments import chain  # noqa: E402
from backend.buy_payments.config import payment_settings as ps  # noqa: E402
from backend.config import settings  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('payment_id', nargs='?')
    ap.add_argument('--tx'); ap.add_argument('--from', dest='payer'); ap.add_argument('--to'); ap.add_argument('--amount-units', type=int)
    ap.add_argument('--reference', default='0x', help="0x-prefixed 32-byte reference; '0x' = plain transfer with no reference")
    a = ap.parse_args()
    if a.payment_id:
        from backend.db import SessionLocal
        from backend.buy_payments.models import BuyPayment
        with SessionLocal() as db: p = db.get(BuyPayment, a.payment_id)
        if not p or not p.tx_hash: sys.exit('Payment not found or has no transaction hash yet')
        tx = p.tx_hash
    else:
        if not (a.tx and a.payer and a.to and a.amount_units): ap.error('give a payment id, or --tx --from --to --amount-units')
        p = SimpleNamespace(chain_id=settings.arc_chain_id, token_address=ps.payment_token_address, payer_address=a.payer,
                            recipient_address=a.to, token_amount=str(a.amount_units), reference=a.reference)
        tx = a.tx
    state, detail = await chain.verify(p, tx, ps.payment_confirmations)
    print(f'chain {p.chain_id} · token {p.token_address}')
    print(f'tx {tx}\n  from {p.payer_address}\n  to   {p.recipient_address}\n  amount {int(p.token_amount) / 10 ** ps.payment_token_decimals} USDC')
    print(f'RESULT: {state}' + (f' ({detail})' if detail is not None else ''))
    print(f'{ps.payment_explorer_url}/tx/{tx}')
    sys.exit(0 if state == 'paid' else 1)

asyncio.run(main())
