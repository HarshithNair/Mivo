# Integration readiness — 6 November 2026

## Gemini — live, verified 6 November 2026
Official key portal: https://aistudio.google.com/apikey
Place GEMINI_API_KEY in root .env (ignored, mode 0600). Never paste credentials into chat.

Live verification: search intent extraction and both agent roles return real structured proposals, and a complete 4-round negotiation across three merchant agents ran against the live API.

Three defects were fixed to get there:
1. Pydantic `gt=0` emits JSON Schema `exclusiveMinimum`, which Gemini's `types.Schema` rejects. The Gemini-facing response schemas now use `ge=1` (identical for integers, so validation strictness is unchanged).
2. `gemini-2.5-flash` is retired for new API users; the endpoint directs callers to a newer flash model.
3. Free-tier quota is per-model and per-day, not merely per-minute. `gemini-3.5-flash` (billed as `gemini-3.6-flash`) allows only 20 requests per DAY, while one negotiation costs roughly 16 calls. The default model is now `gemini-3.1-flash-lite`, which carries its own separate free-tier allowance.

`backend/agents/gemini.py` adds a process-wide pacer (`GEMINI_RPM`, default 5) and retries that honour the server's own `RetryInfo.retryDelay` instead of a guessed backoff. Transient 429/5xx are retried; schema and price-bound violations still fail fast. `NEGOTIATION_ROUNDS` and `NEGOTIATION_DEADLINE` are configurable so a demo can trade negotiation depth against quota.

Quota headroom, not code, is now the limiting factor. Raising it means enabling paid billing on the Google project, which is the user's financial decision and has not been authorized.

## Arc
Verified official network docs: https://docs.arc.io/arc/references/connect-to-arc
Testnet chain ID 5042002, RPC https://rpc.testnet.arc.io (the current official docs use https://rpc.testnet.arc.network; both endpoints were tested and return the same chain ID). Explorer https://explorer.testnet.arc.io. Faucet: https://faucet.circle.com

Verified directly against the live RPC on 6 November 2026:
- `eth_chainId` returns `0x4cef52` (5042002), matching `arc_chain_id`.
- The chain is live and producing blocks (height above 71,000,000).
- The configured settlement token `0x3600...0000` is a real deployed contract that reports `symbol() = "USDC"` and `decimals() = 6`, which matches `settlement_decimals`. This closes the open question above: the ERC-20 interface does expose 6 decimals, distinct from native gas accounting.

Still blocked: the dedicated deployer wallet `0x677f24A555eCA45A85bc1dB1aAbE2EC04fB93553` holds a zero balance, so no contract can be deployed and no settlement can be submitted. This needs testnet funding from the faucet, which requires the user. `payment_enabled()` additionally requires `SETTLEMENT_CONTRACT`, so checkout stays correctly disabled until a real deployment exists. Dedicated testnet wallet only; personal wallets and real funds are excluded. No Arc deployment or payment is claimed.

## 1inch — determined unavailable on Arc, 6 November 2026
Official Mumbai requirements: https://ethglobal.com/events/mumbai/prizes
Sources: https://business.1inch.com/portal/documentation/aqua/liquidity-layer/supported-chains, https://github.com/1inch/aqua, https://github.com/1inch/swap-vm

The official Aqua supported-chains page states `supportedChains = [1, 10, 56, 100, 130, 137, 146, 324, 4663, 8453, 42161, 43114, 59144]` — 13 chains: Ethereum, Optimism, BNB Chain, Gnosis, Unichain, Polygon, Sonic, zkSync Era, Robinhood Chain, Base, Arbitrum, Avalanche, Linea.

Two consequences, both verified rather than assumed:
- Arc testnet (5042002) is **not** an Aqua chain. A 1inch Aqua conversion settled on Arc is therefore not technically possible, and any such flow in this app would be fabricated.
- Aqua lists **no testnets at all**. Demonstrating a genuine Aqua conversion would require a mainnet chain and real funds, which is a financial commitment that has not been authorized.

Conversion therefore remains disabled, with no fabricated quotes and no cross-chain atomicity claims. The checkout UI states plainly that 1inch conversion is not enabled. Direct Arc stablecoin settlement is independent of this and is unaffected.

## World
Official Agent Pass portal: https://auth.world.org/portal
Docs: https://auth.world.org/docs
The current Mumbai page explicitly warns Agent Pass proofs use fake identities for the hackathon. Any such sandbox verification must be labeled and cannot establish genuine human verification. No World application or verified identity has been created.

## Hosting
No deployment yet. Available Sites hosting runs Workers and cannot directly host this FastAPI process. Need an authorized Python hosting account and persistent database plus frontend hosting, or explicit approval to adapt the requested stack. No paid services purchased.
