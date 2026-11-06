# BUY payments: Raspberry Pi → MetaMask → USDC on Arc Testnet

A **BUY** from the Raspberry Pi creates a pending payment. You approve it in **MetaMask** on the Mivo **Payments** page (`/payments`). MetaMask sends a real USDC transfer on **Arc Testnet**. The backend then verifies that transaction on-chain, and only after that does anything show **PAYMENT SUCCESSFUL**, on the website or on the Pi.

Nothing is ever paid automatically: every payment needs your explicit approval in MetaMask. The server never holds a private key.

## Network facts (verified live and against docs.arc.io)

| | |
|---|---|
| Network | Arc Testnet, chain ID **5042002** |
| RPC | `https://rpc.testnet.arc.io` |
| Explorer | `https://explorer.testnet.arc.io` (old `testnet.arcscan.app` redirects here) |
| USDC (ERC-20 interface) | `0x3600000000000000000000000000000000000000`, symbol `USDC`, **6 decimals** |
| Gas | paid in **native USDC, 18 decimals**, from the same balance |

Payments use the 6-decimal ERC-20 `transfer`. A 693.58 USDC deal is `693580000` units, not an 18-decimal value. Each Arc USDC transfer emits **two** `Transfer` events: one from the token (6 decimals) and one from the system address `0xffff…fffe` (18 decimals). The verifier only accepts the token's own event.

## How the transaction is tied to the order

MetaMask sends `transfer(recipient, amount)` with a **32-byte payment reference** appended to the calldata (`keccak256("mivo-buy-payment:" + payment_id)`). The token ignores the extra bytes (tested on Arc Testnet: `eth_call` returns `true`, gas ≈ 49,845), but they are part of the signed transaction. So a transaction can only verify for the one payment it was made for.

## What the backend checks before "paid"

All checks are read from the Arc RPC, never taken from the browser:
1. **Chain:** the RPC reports chain ID 5042002, and the transaction's own `chainId` matches.
2. **Transaction:** it exists, and its hash matches the reported one.
3. **Token:** `to` is the USDC token contract.
4. **Sender:** `from` is the wallet that clicked Approve.
5. **Calldata:** recipient, amount and payment reference match exactly.
6. **Receipt:** `status = 1` (not reverted).
7. **Transfer event:** exactly one `Transfer(payer → recipient, amount)` emitted by the token.
8. **Confirmations:** at least `PAYMENT_CONFIRMATIONS` blocks.
9. **No reuse:** the transaction hash isn't used by any other payment (database unique).

A hash returned by MetaMask only moves the payment to *Transaction submitted*. If the RPC is unreachable or rate-limited, the status simply doesn't change until the next check.

## Statuses

| Backend `status` | Portal label | Pi shows |
|---|---|---|
| (event) | BUY signal received | still waiting |
| `pending` | Payment pending | still waiting |
| `awaiting_approval` | Waiting for MetaMask approval | still waiting |
| `submitted` | Transaction submitted | still waiting |
| `confirming` | Transaction confirming | still waiting |
| `paid` | **PAYMENT SUCCESSFUL** | **PAYMENT SUCCESSFUL** |
| `failed` / `expired` / `rejected` | **PAYMENT FAILED** + reason | **PAYMENT FAILED** + reason |

Failure reasons include:
- **Insufficient balance:** checked on-chain with `balanceOf`.
- **Not enough gas.**
- **Rejected in MetaMask.**
- **Not approved in time:** `PAYMENT_WINDOW`, default 10 min.
- **Transaction not found on-chain in time:** `PAYMENT_TX_TIMEOUT`.
- **Reverted.**
- **Transaction does not match this payment:** includes why.

## Duplicates: never charged twice

- **Same `request_id`:** the same payment is returned.
- **Another BUY for an order already being paid:** the same payment is returned.
- **Order already paid:** `409`.
- **A transaction already sent for the order:** `409`, unless the chain proved it reverted.
- **Another payment still in progress for this buyer:** `429`.
- **A transaction hash already used for another payment:** `409`.
- **After a rejection, an expiry, or an insufficient balance:** no transaction exists yet, so a new BUY (double-press) starts a fresh attempt.
- **Signed but never reported:** if the hash never reached the server (tab closed), the backend finds it on-chain via its `Transfer` log and payment reference.

## API

Device (header `Authorization: Bearer <DEVICE_API_KEY>`), as in `BUY_API.md`:
- `POST /api/device/buy`
  - body: `{"command":"buy","request_id":"<uuid>","negotiation_id":"…","dealer":"…","price_usd":693.58}`
  - reply: `{"status":"pending","payment_id":"PAY_…",…}`
  - The **best (lowest) offer** of that negotiation is bought. `price_usd`/`dealer` are cross-checked (`409` if they differ). The amount always comes from that offer on the server.
- `GET /api/device/payments/{payment_id}`
  - reply: `{status, message, product, dealer, amount, currency:"USDC", network:"Arc Testnet", order_id, recipient, payer, tx_hash, explorer_url, reason}`

Website (logged-in buyer): `GET /api/buy-payments`, `GET /api/buy-payments/{id}`, `POST …/{id}/start`, `POST …/{id}/submit`, `POST …/{id}/report`.

## Configuration (Vercel → Settings → Environment Variables, Production)

| Variable | Required | Value |
|---|---|---|
| `PAYMENT_RECIPIENT_ADDRESS` | **yes** | Public `0x…` address of your **merchant** MetaMask account (receives USDC). Not a secret. |
| `PAYMENT_CONFIRMATIONS` | no | default `1` (Arc has fast finality) |
| `PAYMENT_WINDOW` | no | seconds to approve after BUY, default `600` |
| `PAYMENT_TX_TIMEOUT` | no | seconds a submitted tx may be unseen, default `600` |
| `PAYMENT_TOKEN_ADDRESS` | no | default `0x3600…0000` (official Arc Testnet USDC) |

Already set from earlier work: `DEVICE_API_KEY`, `DEVICE_BUYER_EMAIL`, `DATABASE_URL`. `ARC_RPC_URL` and `ARC_CHAIN_ID` default to the values above.

**Never** put a private key or seed phrase in any environment variable. None is needed.

Database: run `.venv/bin/alembic upgrade head` (adds the `buy_payments` table, migration `005`).

## MetaMask setup (two accounts on your device)

1. **Accounts:** in MetaMask, use (or **Add account**) two accounts: rename one **Mivo Buyer** and one **Mivo Merchant**.
2. **Recipient:** copy the **Merchant** account's address into `PAYMENT_RECIPIENT_ADDRESS` in Vercel, then redeploy.
3. **Add Arc Testnet:** on the Payments page, click **Connect MetaMask**, then **Switch to Arc Testnet**. MetaMask offers to add the network. To add it manually instead:
   - Network name `Arc Testnet`
   - RPC `https://rpc.testnet.arc.io`
   - Chain ID `5042002`
   - Currency symbol `USDC`
   - Explorer `https://explorer.testnet.arc.io`
4. **Pay from the Buyer:** select the **Buyer** account when approving. The server refuses payments from the merchant (recipient) address.

## Getting testnet USDC (Circle faucet)

1. Open **https://faucet.circle.com/**.
2. Choose **USDC** and the network **Arc Testnet**.
3. Paste the **Mivo Buyer** address and request funds.
4. Check the balance on the Payments page, or at `https://explorer.testnet.arc.io/address/<buyer address>`.

The same USDC balance pays the deal and the gas.

## End-to-end test

1. **Pi:** scan, negotiate, then double-press within 30 s. The Pi shows a pending payment ID.
2. **Website:** log in as `DEVICE_BUYER_EMAIL` and open **Payments**. The card shows the product, amount, recipient and *Payment pending*.
3. **Approve:** connect MetaMask (Buyer account, Arc Testnet), click **Approve … USDC in MetaMask**, and confirm in MetaMask.
4. **Watch it settle:** the status goes *Transaction submitted → Transaction confirming → PAYMENT SUCCESSFUL*, with the hash and explorer link. The Pi shows **PAYMENT SUCCESSFUL** on its next poll.
5. **Verify independently:** `.venv/bin/python scripts/verify_arc_payment.py PAY_…` (with `DATABASE_URL` set) re-runs every check.

Failure tests:
- **Insufficient funds:** approve from an account with less USDC than the deal.
- **Rejected:** press *Reject* in MetaMask.
- **Duplicate BUY:** double-press again; the Pi gets the same `payment_id`.
