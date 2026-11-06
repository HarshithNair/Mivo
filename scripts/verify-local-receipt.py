import asyncio,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import settings
from backend.services.payments import verified_receipt
settings.arc_rpc_url='http://127.0.0.1:8547'
data=json.loads(Path('docs/local-settlement.json').read_text())
assert data['chain_id']==31337
receipt=asyncio.run(verified_receipt(SimpleNamespace(**data),data['transaction_hash']))
assert int(receipt['status'],16)==1
print('PASS: Python backend independently verified the local settlement receipt, event and confirmations')
