# Raspberry Pi product identification

The Pi POSTs a photo over HTTPS; Gemini identifies the product using Google Search grounding; the details come back **in the response to that same request** (no callback URL needed, so the Pi does not have to be reachable from the internet).

## Endpoint
`POST https://<your-app>/api/device/identify`

| Header | Value |
|---|---|
| `Authorization` | `Bearer <DEVICE_API_KEY>` |
| `Content-Type` | `image/jpeg`, `image/png` or `image/webp` |

Body: the **raw image bytes** (not multipart), max 4 MB.

```sh
curl -X POST https://<your-app>/api/device/identify \
  -H "Authorization: Bearer $MIVO_DEVICE_KEY" -H "Content-Type: image/jpeg" \
  --data-binary @photo.jpg
```
Or use [`scripts/rpi_identify.py`](../scripts/rpi_identify.py) (stdlib only; `--capture` takes a photo with `rpicam-still`).

## Response (200)
```json
{
  "identified": true,
  "name": "…", "brand": "…", "model": "…", "category": "…", "description": "…",
  "key_features": ["…"],
  "price_range_usd": {"low": 129.0, "high": 149.0},
  "where_to_buy": ["…"],
  "confidence": 0.85,
  "web_search": true,
  "sources": [{"title": "…", "url": "…"}],
  "catalog_matches": [{"id": "…", "name": "…", "merchant": "…", "price_cents": 14900}]
}
```
`catalog_matches` are Mivo products whose name matches, so the device can hand off into a negotiation.

## Negotiate: `?negotiate=true`

`POST /api/device/identify?negotiate=true` (optional `&budget_usd=750`) does the identification above, then:

1. Creates demo dealers (default 3, `DEVICE_DEALERS`) selling the identified product. Each gets a listing price around Gemini's price estimate and a private minimum below it. They are labelled `· Demo`, and their listings are hidden from the Discover catalog.
2. Runs the normal AI negotiation (`NEGOTIATION_ROUNDS`) on behalf of the buyer account in **`DEVICE_BUYER_EMAIL`**. Server rules keep every offer between the dealer's minimum and listing.
3. Returns the best offer in the same response, under `negotiation`:

```json
"negotiation": {
  "id": "…", "status": "completed", "budget_usd": 728.64,
  "dealers": [{"name": "Urban Gadget Hub · Demo", "listing_usd": 857.22}],
  "best_offer": {"dealer": "Urban Gadget Hub · Demo", "price_usd": 761.94, "listing_usd": 857.22, "savings_usd": 95.28, "expires_at": 1793996146},
  "offers": [ "…all offers, cheapest first…" ],
  "deal_room_url": "https://<your-app>/deal-room?id=…"
}
```
`status` is `completed`, `failed` (no valid offers), or `skipped`, with a `reason` when nothing was recognised or no price estimate was available.

Without `budget_usd`, the budget is 85% of the cheapest dealer listing. The negotiation is stored like any other: log in on the website as `DEVICE_BUYER_EMAIL` to see it in **My Deals / Deal Room** and to **accept** an offer (offers expire after 10 minutes; nothing is accepted automatically).

Cost and time: one identification call plus `NEGOTIATION_ROUNDS × (1 + dealers)` Gemini calls (9 by default), paced by `GEMINI_RPM`. Expect 2–4 minutes; set the client timeout to ~290 s. A new scan of the same product retires the previous scan's demo dealers. At most 2 negotiations can run at once per buyer (`429` otherwise).

## Errors
`401` wrong/missing key · `422` invalid `budget_usd` · `413` image > 4 MB · `415` not a JPEG/PNG/WebP (checked by file signature) · `429` rate limited · `502` Gemini failed or quota exhausted · `503` `DEVICE_API_KEY` or `GEMINI_API_KEY` not set, or (with `negotiate`) `DEVICE_BUYER_EMAIL` missing or not a buyer account.

## Notes
- **`web_search`:** Google Search grounding has a much smaller free-tier quota than plain Gemini calls. When it is exhausted (429), the server identifies the product from the model's own knowledge instead and returns `"web_search": false` with empty `sources`. Identification still works, but prices and retailers may be out of date.
- Each scan is one Gemini call with Google Search grounding, sharing the same free-tier quota as negotiations.
- Rate limit is 20 requests/minute per IP, per server instance.
- Prices and retailers come from live search and the model's reading of it; treat them as estimates. Source links are Google grounding redirect URLs.
