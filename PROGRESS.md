# Mivo progress

## Implemented
- Shared npm/Python monorepo, Git initialization, SQLite migrations and seeded demo catalog (3 demo merchants, 12 products).
- Password authentication, private sessions, origin and ownership checks, merchant catalog and saved products.
- Separate Gemini buyer/merchant negotiation logic, server-enforced price constraints, persisted events, cancellation, expiry and explicit quote acceptance.
- Responsive cream/purple/orange interface, with all 11 app sections routed (discover, deal-room, my-deals, wallet, checkout, profile, login, signup, merchant, orders, world-callback).
- Dedicated testnet wallet and quote signer stored in ignored private files; no personal wallet or real funds used.
- Signed settlement contract and backend receipt verification, wallet ownership proofs, checkout intents and orders. A real local Anvil settlement was independently verified; no public Arc deployment or payment is claimed.
- World authorization-code integration with PKCE, signed-token validation, single-use state and separate sandbox labeling.

## Verified live this session (6 November 2026)
- **Gemini is live and a full negotiation completed end to end.** A 4-round, 3-merchant negotiation ran against the real API in 213.6s: 17 persisted events, 3 final offers, every offer at or above its merchant's private floor, best offer $139.00 against a $149.00 listing. One transient upstream timeout was retried and recovered automatically.
- Three real defects were fixed to get there: Pydantic `gt=0` emitted `exclusiveMinimum`, which Gemini's schema validator rejects; `gemini-2.5-flash` is retired for new API users; and free-tier quota is per-model **per-day** (20/day on the 3.5/3.6 flash line) against roughly 16 calls per negotiation.
- Arc testnet verified directly against the live RPC: `eth_chainId` = `0x4cef52` (5042002) matches config, the chain is producing blocks past height 71,000,000, and the configured settlement token reports `symbol() = "USDC"` with `decimals() = 6`, matching `settlement_decimals`.
- 44 backend tests pass. One previously "passing" test (`test_no_fake_ai`) only held while `GEMINI_API_KEY` was absent from the environment; it now forces the unconfigured state explicitly, so the fail-closed guarantee is tested deterministically.
- 12 Foundry contract tests pass (replay, wrong chain, wrong merchant, wrong amount, expiry, spending cap, duplicate settlement, insufficient balance, invalid signature).
- 6 browser tests pass, including a new World test asserting the honest unconfigured state and that a forged callback fails closed rather than reporting a verified human.
- Frontend build, typecheck and lint all pass clean.

## External blockers (need the user)
- **Gemini quota.** The code is correct; free-tier headroom is the limit. At the new 2-round default a negotiation costs 8 calls against 3 merchants (it was 16 at 4 rounds, which measured 213.6s end to end); wall-clock time scales with the `GEMINI_RPM` pacing needed to stay inside quota. Raising this means enabling paid billing on the Google project — a financial decision that has not been authorized. `NEGOTIATION_ROUNDS` now defaults to **2** (8 calls per negotiation) to keep the demo practical on free tier.
- **Arc funding.** Deployer `0x677f24A555eCA45A85bc1dB1aAbE2EC04fB93553` has a zero balance, so no contract deployment or on-chain settlement is possible. Needs faucet funding (https://faucet.circle.com).
- **World credentials.** No developer app exists, so `WORLD_CLIENT_ID`/`WORLD_CLIENT_SECRET` are empty and `/world/start` correctly returns 503.
- **1inch.** Now definitively resolved against official docs: Aqua runs on 13 mainnet chains and **no testnets**, and Arc (5042002) is not one of them. A 1inch conversion settled on Arc is not technically possible. Demonstrating Aqua at all would need a mainnet chain and real funds — an unauthorized financial commitment. Conversion stays disabled.
- **Hosting.** No deployment. Needs an authorized Python host plus persistent database, or approval to adapt the stack.

## Known wrinkle, not yet changed
Final-round offers are persisted even when above the buyer's stated budget (one offer came back at $141.00 against a $140.00 budget). Merchant floors are still enforced and the buyer must accept explicitly, so this is a comparison/UX question rather than a safety one. Flagged rather than silently changed.

## Next
Fund the Arc wallet and deploy the settlement contract, create the World developer app, decide on Gemini billing versus reduced negotiation depth, then prepare hosting and deployment configuration. Require user participation for credentials, account login, wallet signatures, paid services and irreversible actions.
