# Raspberry Pi client: build brief

Build a small program on this Raspberry Pi that takes a photo, sends it over HTTPS to the Mivo server, and prints/uses the product details the server sends back. The server does all the AI work (Gemini + web search); the Pi only captures, uploads and reads the JSON reply.

## 1. Configuration (environment variables, never hard-coded)

| Variable | Value |
|---|---|
| `MIVO_URL` | `https://mivo-harshithnair0307-6911s-projects.vercel.app` |
| `MIVO_DEVICE_KEY` | the device key (ask the owner; it is secret — do not commit it, print it or log it) |

Store them in `~/.config/mivo/env` with `chmod 600`, and load that file before running.

## 2. Capture a photo

- Pi camera module (Bookworm or newer): `rpicam-still -n -t 1000 --width 1280 --height 960 -q 85 -o /tmp/mivo.jpg`
  (older OS: `libcamera-still` with the same flags)
- USB webcam: `fswebcam -r 1280x960 --no-banner /tmp/mivo.jpg`

Requirements for the image:
- JPEG (preferred), PNG or WebP.
- **Must be 4 MB or smaller.** 1280×960 JPEG at quality 85 is typically 200–600 KB. If larger, re-encode smaller before sending.
- Product should fill most of the frame, in good light. Visible labels/model numbers help a lot.

## 3. Send it

```
POST {MIVO_URL}/api/device/identify
Authorization: Bearer {MIVO_DEVICE_KEY}
Content-Type: image/jpeg            (or image/png, image/webp — must match the file)
Body: the raw image bytes
```

- Body is the **raw file bytes**, NOT multipart/form-data and NOT base64.
- HTTPS only. Do not disable certificate verification.
- **Client timeout: 120 seconds.** A normal reply takes 15–30 s; the server can take longer while it retries Gemini.
- Send one image at a time; wait for the reply before sending the next.

Reference command:
```sh
curl -sS --max-time 120 -X POST "$MIVO_URL/api/device/identify" \
  -H "Authorization: Bearer $MIVO_DEVICE_KEY" \
  -H "Content-Type: image/jpeg" \
  --data-binary @/tmp/mivo.jpg
```

## 4. Read the reply (HTTP 200, JSON)

```json
{
  "identified": true,
  "name": "Apple iPhone 15 Pro",
  "brand": "Apple",
  "model": "iPhone 15 Pro",
  "category": "Smartphone",
  "description": "A pre-owned Apple iPhone 15 Pro in Natural Titanium, 128GB ...",
  "key_features": ["128GB storage", "Natural Titanium finish"],
  "price_range_usd": {"low": 800.0, "high": 900.0},
  "where_to_buy": ["Apple Store", "Authorized retailers"],
  "confidence": 1.0,
  "web_search": false,
  "sources": [],
  "catalog_matches": []
}
```

| Field | Meaning |
|---|---|
| `identified` | `false` = no product recognised; other fields will be mostly null. Ask the user to retake the photo. |
| `name`, `brand`, `model`, `category`, `description` | strings or `null` |
| `key_features`, `where_to_buy` | lists of strings (max 10), may be empty |
| `price_range_usd` | `{"low": number|null, "high": number|null}` or `null`. An estimate, not a quote. |
| `confidence` | 0.0–1.0 |
| `web_search` | `true` = details checked against live web search; `false` = model knowledge only, so prices/retailers may be out of date. Show this to the user. |
| `sources` | `[{"title", "url"}]` web pages used (empty when `web_search` is false) |
| `catalog_matches` | `[{"id", "name", "merchant", "price_cents"}]` matching products sold on Mivo (`price_cents` ÷ 100 = USD) |

Treat every field as possibly `null`/empty; never crash on a missing value.

## 4b. Negotiating: `?negotiate=true`

Add `?negotiate=true` (and optionally `&budget_usd=750`) to the URL to also have Mivo haggle with demo dealers. The reply then includes a `negotiation` object with `status`, `best_offer` (`dealer`, `price_usd`, `listing_usd`, `savings_usd`), all `offers`, and a `deal_room_url` where the owner accepts the deal on the website. This usually takes 30–60 seconds; still use a **290-second timeout** and do not retry a 429 automatically. Full field list: `docs/DEVICE.md` in the repo.

## 5. Errors: what to do

Error bodies are usually JSON (`{"detail": "message"}`), but very large uploads or hosting-level failures can return plain text, so parse defensively.

| Status | Meaning | Action |
|---|---|---|
| 401 | Wrong or missing device key | Stop. Do not retry. Report "device key rejected". |
| 413 | Image over 4 MB | Re-encode smaller (lower resolution/quality), then resend once. |
| 415 | Not a valid JPEG/PNG/WebP, or `Content-Type` doesn't match the file | Fix the file/header. Do not retry unchanged. |
| 429 | Too many requests (limit 20/minute) | Wait 60 s, then retry. |
| 502 | AI service temporarily failed | Retry up to 2 more times, waiting 15 s then 30 s. |
| 503 | Server not configured | Stop; report to the owner. |
| network error / timeout | — | Retry up to 2 more times with the same waits as 502. |

## 6. Deliverable

1. A Python 3 script (`mivo_identify.py`) using **only the standard library** (`urllib.request`, `json`, `subprocess`), so nothing needs `pip install`. It should:
   - `python3 mivo_identify.py photo.jpg` → send an existing file
   - `python3 mivo_identify.py --capture` → take a photo, then send it
   - print a short human-readable summary (name, price range, confidence, whether web search was used), and with `--json` print the raw JSON
   - exit code 0 on success, non-zero on failure, following the error table above
2. Optional: trigger capture from a GPIO push-button (e.g. `gpiozero.Button(17)`), and/or run as a `systemd` service that loads `~/.config/mivo/env`.

A working minimal reference already exists at `scripts/rpi_identify.py` in the Mivo repo (https://github.com/HarshithNair/Mivo); extend it rather than starting from scratch if convenient.

## 7. Acceptance test

1. `curl -s "$MIVO_URL/api/health"` returns `"status":"ok"` and `"device_configured":true`.
2. Photographing a common product (phone, headphones, bottle) returns HTTP 200 with `"identified": true` and a sensible `name`.
3. Running with a wrong key returns 401 and the script exits non-zero **without retrying**.
4. Sending a text file renamed `.jpg` returns 415.
