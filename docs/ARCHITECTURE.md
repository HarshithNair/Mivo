# Architecture

One npm workspace and Python package in one Git repository. Next.js 15 owns UI; FastAPI owns authorization, catalog queries, negotiation state and quotes. SQLite is migrated by Alembic. Amounts are integer USD cents in catalog/quotes; chain token units must be converted using verified decimals at the payment boundary.

## Trust boundaries
- Passwords: Argon2. Sessions: random opaque tokens, only SHA-256 hashes persisted. HttpOnly SameSite=Strict cookies; secure flag required over HTTPS.
- Same-origin Next.js API proxy. Unsafe requests require the configured Origin. WebSockets check Origin and the session and negotiation owner.
- Public product serializers omit private floors. Merchant policies enter only that merchant agent's prompt. Buyer agents never see floors.
- Gemini proposals contain numeric amounts only. Server rejects invalid bounds, rather than relaying model-generated text that might disclose private policies.
- Only explicit buyer acceptance creates a quote. Atomic status update and uniqueness prevent multiple accepted quotes. Payment remains disabled until receipt verification is wired and tested.
- Settlement contract uses EIP-712 chain/contract domain binding, buyer sender binding, immutable token/signer/cap, expiry, nonce and quote replay prevention, SafeERC20 and reentrancy protection.

## Current limits
Single backend process. Jobs are in-process and visibly fail after restart; no distributed worker lease or shared rate-limit store. Before public deployment: shared durable jobs/limits, account recovery and email verification, transactional stock reservation, complete receipt reconciliation, audit/log monitoring and deployment security review are still required. Initial migration imports current metadata; freeze subsequent migrations before schema evolution.

## Frontend
Local SVG illustrations are representative assets, not official retailer imagery. No fabricated discount badges, paid orders, transaction hashes or verification claims. Product prices and counts come from backend queries. Wagmi connects only an injected browser wallet to Arc testnet; no payment action is wired yet.
