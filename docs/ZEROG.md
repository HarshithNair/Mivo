# 0G in MIVO

**Compute:** buyer, merchant and dealer negotiation decisions run on the **0G Compute Router** (OpenAI-compatible, `0gm-1.0-35b-a3b`). Each decision is logged with the router's `request_id`, provider address and model.
**Storage:** sanitized negotiation evidence is uploaded to **0G Storage** (testnet, chain 16602) with the official SDK, downloaded back with a Merkle proof, hash-checked, and its root hash is recorded.

## Rules
- **Merchant floors and buyer identity never leave the server.** The model sees only public numbers and returns a *concession* (0–1). The server turns it into a price inside `[floor, last price]` (buyers: never above budget).
- **Invalid output, a timeout or an HTTP error from 0G** → the existing Gemini agent decides, and the log records `provider=gemini` plus the reason. If Gemini fails too, the existing engine drops that merchant or fails the negotiation. Nothing is invented.
- **AI never authorizes payment.** Only completed, server-validated offers reach the existing BUY → MetaMask → Arc flow, which is unchanged.

## Configure
| Variable | Value |
|---|---|
| `ZEROG_API_KEY` | Router key (`sk-…`) from pc.0g.ai (mainnet) or pc.testnet.0g.ai |
| `ZEROG_ROUTER_URL` | default `https://router-api.0g.ai/v1` (testnet: `https://router-api-testnet.integratenetwork.work/v1`) |
| `ZEROG_MODEL` | default `0gm-1.0-35b-a3b` |
| `ZEROG_TIMEOUT`, `ZEROG_RETRIES` | default `25`, `1` |
| `ZEROG_ENABLED` | `false` forces Gemini |

Unset `ZEROG_API_KEY` = exactly the previous Gemini behaviour.

Database: `.venv/bin/alembic upgrade head` (migration `006`: `zerog_decisions`, `zerog_evidence`).

## Run
```sh
ZEROG_API_KEY=sk-… .venv/bin/python scripts/zerog_live_check.py     # real inference + a real negotiation on a scratch DB
cd integrations/zerog/storage && npm install
node new-wallet.mjs                                                   # dedicated storage-fee wallet; fund it from the 0G faucet
MIVO_URL=https://… MIVO_DEVICE_KEY=… node upload-evidence.mjs <negotiation_id>   # local API: run `uvicorn backend.vercel_app:app` so /api/... paths match production
node verify.mjs <root_hash> <sha256>                                  # independent download + proof + hash check
```

## Endpoints
| Endpoint | Who | Purpose |
|---|---|---|
| `GET /api/zerog/status` | public | config and model availability |
| `GET /api/negotiations/{id}/zerog` | owner | per-decision provider, request_id, latency, fallback |
| `GET /api/negotiations/{id}/zerog/evidence` | owner | 0G Storage root hashes |
| `GET /api/device/zerog/evidence/{id}` | device key | sanitized evidence + canonical bytes + sha256 |
| `POST /api/device/zerog/evidence/{id}/stored` | device key | record a root hash; accepted only when verified and the hash matches |

## Verified run (0G Galileo testnet, chain 16602)
Real negotiation `9b321314-5f98-47e5-a120-11eaffa799b5` (scratch DB, Gemini decisions), 1,261-byte sanitized evidence:
- root `0xc6ccec2fa1932885478f71f32e501b45c2f3b67a55686e361e30964a248a8940`
- tx `0xd3859a1c3b2a669e923124d0cb3249552f5c43090880a92ef30975b768e34716` (success, block 64,250,466, flow contract `0x22E03a6A89B950F1c82ec5e74F8eCa321a105296`, fee 0.00124 0G)
- downloaded from 0G storage nodes with Merkle proof, twice; sha256 `0xa88e56370a85083f86c6da6e02aa9baac10950061b9b1759501ff3d0630b0fd3` matched both times
