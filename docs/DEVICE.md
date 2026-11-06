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

## Errors
`401` wrong/missing key · `413` image > 4 MB · `415` not a JPEG/PNG/WebP (checked by file signature) · `429` rate limited · `502` Gemini failed or quota exhausted · `503` `DEVICE_API_KEY` or `GEMINI_API_KEY` not set.

## Notes
- **`web_search`:** Google Search grounding has a much smaller free-tier quota than plain Gemini calls. When it is exhausted (429), the server identifies the product from the model's own knowledge instead and returns `"web_search": false` with empty `sources`. Identification still works, but prices and retailers may be out of date.
- Each scan is one Gemini call with Google Search grounding, sharing the same free-tier quota as negotiations.
- Rate limit is 20 requests/minute per IP, per server instance.
- Prices and retailers come from live search and the model's reading of it; treat them as estimates. Source links are Google grounding redirect URLs.
