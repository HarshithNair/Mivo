# Integration readiness — 6 November 2026

## Gemini
Official key portal: https://aistudio.google.com/apikey
Place GEMINI_API_KEY in root .env (ignored, mode 0600). Never paste credentials into chat. Gemini search and two agent roles are implemented; external API tests are pending the user's login/key. No paid billing authorized.

## Arc
Verified official network docs: https://docs.arc.io/arc/references/connect-to-arc
Testnet chain ID 5042002, RPC https://rpc.testnet.arc.io, explorer https://explorer.testnet.arc.io. Native gas USDC has 18 decimals; do not confuse native gas decimals with an ERC20 interface. Token contract/decimals must be verified before deploying checkout. Faucet: https://faucet.circle.com
Local settlement implementation exists; no Arc deployment or funding has occurred. Dedicated testnet wallet only. Personal wallets and real funds are excluded.

## 1inch
Official Mumbai requirements: https://ethglobal.com/events/mumbai/prizes
Aqua/SwapVM contracts and demonstrated on-chain token transfers required; a generic swap API is insufficient. Sources: https://github.com/1inch/aqua and https://github.com/1inch/swap-vm
Arc compatibility and genuine conversion route have not been verified. Conversion remains disabled, without fabricated quotes or cross-chain atomicity claims.

## World
Official Agent Pass portal: https://auth.world.org/portal
Docs: https://auth.world.org/docs
The current Mumbai page explicitly warns Agent Pass proofs use fake identities for the hackathon. Any such sandbox verification must be labeled and cannot establish genuine human verification. No World application or verified identity has been created.

## Hosting
No deployment yet. Available Sites hosting runs Workers and cannot directly host this FastAPI process. Need an authorized Python hosting account and persistent database plus frontend hosting, or explicit approval to adapt the requested stack. No paid services purchased.
