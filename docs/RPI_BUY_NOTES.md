# BUY: what the live server actually does (notes for the Pi)

These notes are for the Pi code built from `BUY_API.md`. The server is **live** and follows `BUY_API.md`; this file lists the details and differences the Pi should handle.

Server: `https://mivo-harshithnair0307-6911s-projects.vercel.app`
Payments page (where the owner approves in MetaMask): `https://mivo-harshithnair0307-6911s-projects.vercel.app/payments`

## 1. Network and currency are Arc Testnet / USDC, not Sepolia

Replies say `"network": "Arc Testnet"` and `"currency": "USDC"`, and `explorer_url` points to `https://explorer.testnet.arc.io/tx/…`. Show whatever the server sends; don't hard-code "Sepolia" or "tUSDC".

## 2. What to send in `POST /api/device/buy`

```json
{
  "command": "buy",
  "request_id": "<new UUID per double-press>",
  "negotiation_id": "<negotiation.id from the negotiate reply>",
  "offer_id": null,
  "dealer": "<negotiation.best_offer.dealer, unchanged>",
  "price_usd": <negotiation.best_offer.price_usd, unchanged>,
  "deal_room_url": "<negotiation.deal_room_url>"
}
```
- **`negotiation_id`:** the negotiate reply already includes it, as `negotiation.id`.
- **`offer_id`:** ignored. The server always buys the negotiation's **best (lowest) offer**, which is the `best_offer` the Pi showed.
- **`price_usd` and `dealer` are cross-checked.** Copy them exactly from `best_offer`, with no rounding or reformatting. If they don't match the server's deal, you get **409** with `Price changed: …` or `Dealer changed: …`.
- **`request_id`:** 8–80 characters from `A–Z a–z 0–9 . _ : -` (a UUID is fine). Sending the same `request_id` again returns the same payment.

## 3. The BUY reply: the owner must approve on the website

```json
{"status": "pending", "payment_id": "PAY_…", "message": "Payment request created. Approve it in MetaMask on the Mivo Payments page.", "product": "…", "dealer": "…", "amount": "18.40", "currency": "USDC", "network": "Arc Testnet", "order_id": "PAY_…", "recipient": "0x…", "payer": null, "tx_hash": null, "explorer_url": null, "reason": null}
```
The Pi cannot pay by itself. **Show the `message`** (and ideally the Payments page URL above) so the owner knows to open the website and approve in MetaMask.

**A double-press while a payment for the same deal is already running** returns **200 with the same `payment_id`**. Just resume polling it. No second payment is created.

## 4. Error codes, including one that isn't in BUY_API.md

| Code | When | Pi should show |
|---|---|---|
| 401 | wrong device key | Device key rejected |
| **404** | **negotiation not found** (not in BUY_API.md's table) | "Not possible: <detail>", same as 409 |
| 409 | already paid, price/dealer changed, a transaction already sent, negotiation not ready | "Not possible: <detail>" |
| 410 | offer or accepted deal expired: negotiate again | "Not possible: <detail>" |
| 422 | bad body (e.g. `request_id` too short) | "Request rejected: <detail>" |
| 429 | another payment still in progress, **or** too many requests (20/min) | "Busy: <detail>" |
| 503 | server setting missing (recipient wallet / buyer account) | "Server not configured: <detail>" |

Keep **never retrying BUY automatically**. That's still right.

## 5. Polling `GET /api/device/payments/{payment_id}`

- **Safe to retry on network errors** (it's a GET; unlike BUY, it never creates anything).
- **Waiting statuses** you'll see, in order:
  - `pending`: Payment pending
  - `awaiting_approval`: Waiting for MetaMask approval
  - `submitted`: Transaction submitted
  - `confirming`: Transaction confirming

  Show the reply's `message`, which carries those labels.
- **Final:** `paid` → **PAYMENT SUCCESSFUL**. `failed`, `expired` or `rejected` → **PAYMENT FAILED** with `reason`.
- **404** means an unknown `payment_id`.
- Extra fields you can display: `product`, `recipient`, `payer` (the MetaMask wallet that paid), `tx_hash`, `explorer_url`, `order_id` (same as `payment_id`).
- `paid` is only returned after the server has verified the transaction **on-chain**. A MetaMask hash alone shows as `submitted`.

## 6. Timing

- The owner has **10 minutes** after BUY to approve; then the status becomes `expired`. That matches the Pi's 10-minute poll.
- After approval, Arc confirms in seconds. If the Pi's 10 minutes run out while the status is `submitted` or `confirming`, tell the user to check the Payments page. Don't show it as failed.

## 7. Funds: keep deals under ~19.9 USDC for now

The buyer wallet holds **20 test USDC**, and the payment amount is the **negotiated price**. Anything above about 19.9 USDC (leaving room for gas) ends as `failed` with reason `Insufficient USDC balance: wallet has …, needs …`. Optional: if `best_offer.price_usd > 19.9`, warn on screen before accepting the double-press.

## 8. Retrying after a failure

After `rejected`, `expired` or an insufficient-balance failure, no money moved. A **new double-press** (new `request_id`) creates a fresh attempt with a **new `payment_id`**, as long as the deal hasn't expired (410 if it has: negotiate again). After `paid`, BUY returns 409 "already bought".
