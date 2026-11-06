# Mivo on Raspberry Pi: setup guide

Point the Pi's camera at a product, and Mivo tells you what it is: name, model, features, an estimated price and where to buy it.
The Pi takes the photo and sends it over HTTPS. The Mivo server does the AI work (Gemini) and sends the details back.

**You need:** a Raspberry Pi with internet access, Raspberry Pi OS (Bookworm or newer recommended), a Pi camera module or USB webcam, and the **device key** from the Mivo owner.

---

## Step 1: Check the Pi can reach Mivo

```sh
curl -s https://mivo-harshithnair0307-6911s-projects.vercel.app/api/health
```
You should see `"status":"ok"` and `"device_configured":true`.

## Step 2: Check the camera

```sh
rpicam-still -n -t 1000 --width 1280 --height 960 -o ~/test.jpg && ls -lh ~/test.jpg
```
- Older Pi OS: use `libcamera-still` instead of `rpicam-still`.
- USB webcam: `sudo apt install -y fswebcam`, then `fswebcam -r 1280x960 --no-banner ~/test.jpg`.

## Step 3: Save your settings

Replace `PASTE_DEVICE_KEY_HERE` with the real key. The key is secret: don't share it or put it in git.

```sh
mkdir -p ~/.config/mivo
cat > ~/.config/mivo/env <<'ENV'
export MIVO_URL=https://mivo-harshithnair0307-6911s-projects.vercel.app
export MIVO_DEVICE_KEY=PASTE_DEVICE_KEY_HERE
ENV
chmod 600 ~/.config/mivo/env
```

## Step 4: Install the script

Run this whole block. It writes the script to `~/mivo/mivo_identify.py`. It uses only Python's standard library, so there's nothing to `pip install`.

```sh
mkdir -p ~/mivo
cat > ~/mivo/mivo_identify.py <<'PYEOF'
#!/usr/bin/env python3
"""Mivo Raspberry Pi client: photograph a product, send it to Mivo, print the details.

Standard library only. Needs MIVO_URL and MIVO_DEVICE_KEY in the environment.

    python3 mivo_identify.py photo.jpg        send an existing image
    python3 mivo_identify.py --capture        take a photo with the camera, then send it
    add --negotiate                           also haggle with demo dealers and return the best deal
    add --budget 750                          your budget in USD for --negotiate (optional)
    add --json                                print the raw JSON reply instead of a summary

Exit codes: 0 ok, 1 usage/config, 2 rejected (bad key/image), 3 server/network failure.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
MAX_BYTES = 4 * 1024 * 1024
RETRY_WAITS = (15, 30)  # for 502 / network errors: two retries
TIMEOUT = 120
NEGOTIATE_TIMEOUT = 290  # a negotiation runs ~2-4 minutes on the server


class Fatal(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def capture():
    path = os.path.join(tempfile.gettempdir(), 'mivo-capture.jpg')
    for tool in ('rpicam-still', 'libcamera-still'):
        if shutil.which(tool):
            cmd = [tool, '-n', '-t', '1000', '--width', '1280', '--height', '960', '-q', '85', '-o', path]
            break
    else:
        if not shutil.which('fswebcam'): raise Fatal('No camera tool found (rpicam-still, libcamera-still or fswebcam)', 1)
        cmd = ['fswebcam', '-q', '-r', '1280x960', '--no-banner', path]
    try: subprocess.run(cmd, check=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e: raise Fatal(f'Camera capture failed: {e}', 1)
    return path


def detail(body):
    try: return json.loads(body).get('detail') or body
    except (ValueError, AttributeError): return body.strip()[:200] or 'no details'


def send(path, url, key, negotiate=False, budget=None):
    mime = TYPES.get(os.path.splitext(path)[1].lower())
    if not mime: raise Fatal('Use a .jpg, .jpeg, .png or .webp image', 1)
    with open(path, 'rb') as f: body = f.read()
    if len(body) > MAX_BYTES: raise Fatal(f'Image is {len(body) // 1024} KB; it must be 4 MB or smaller', 2)
    query = {'negotiate': 'true', **({'budget_usd': budget} if budget else {})} if negotiate else {}
    endpoint = url.rstrip('/') + '/api/device/identify' + ('?' + urllib.parse.urlencode(query) if query else '')
    request = urllib.request.Request(endpoint, data=body, method='POST',
                                     headers={'Content-Type': mime, 'Authorization': 'Bearer ' + key, 'User-Agent': 'mivo-pi/1.0'})
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=NEGOTIATE_TIMEOUT if negotiate else TIMEOUT) as response: return json.load(response)
        except urllib.error.HTTPError as e:
            message = detail(e.read().decode(errors='replace'))
            if e.code == 401: raise Fatal('Device key rejected (401). Check MIVO_DEVICE_KEY.', 2)
            if e.code in (413, 415, 422): raise Fatal(f'Request rejected ({e.code}): {message}', 2)
            if e.code == 503: raise Fatal(f'Server not configured (503): {message}', 3)
            if e.code == 429 and negotiate: raise Fatal(f'Busy (429): {message}', 3)
            if e.code == 429: wait = 60
            elif e.code == 502 and attempt < len(RETRY_WAITS): wait = RETRY_WAITS[attempt]
            else: raise Fatal(f'Server error ({e.code}): {message}', 3)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt >= len(RETRY_WAITS): raise Fatal(f'Network error: {getattr(e, "reason", e)}', 3)
            wait = RETRY_WAITS[attempt]
        attempt += 1
        if attempt > 3: raise Fatal('Gave up after repeated failures', 3)
        print(f'Retrying in {wait}s…', file=sys.stderr); time.sleep(wait)


def summary(r):
    if not r.get('identified'): return 'No product recognised. Try again with the product filling the frame and better light.'
    lines = [r.get('name') or 'Unknown product']
    maker = ' · '.join(x for x in (r.get('brand'), r.get('model'), r.get('category')) if x)
    if maker: lines.append(maker)
    if r.get('description'): lines.append(r['description'])
    for feature in r.get('key_features') or []: lines.append('  • ' + feature)
    price = r.get('price_range_usd') or {}
    if price.get('low') is not None or price.get('high') is not None:
        low, high = price.get('low'), price.get('high')
        lines.append('Price: ' + (f'${low:,.0f}–${high:,.0f}' if low is not None and high is not None else f'${(low if low is not None else high):,.0f}') + ' (estimate)')
    if r.get('where_to_buy'): lines.append('Where to buy: ' + ', '.join(r['where_to_buy']))
    lines.append(f"Confidence: {round(100 * (r.get('confidence') or 0))}%  ·  " + ('checked with live web search' if r.get('web_search') else 'no web search used; prices may be out of date'))
    for s in (r.get('sources') or [])[:3]: lines.append(f"  source: {s.get('title') or ''} {s.get('url') or ''}".rstrip())
    for m in r.get('catalog_matches') or []: lines.append(f"On Mivo: {m.get('name')} from {m.get('merchant')} at ${m.get('price_cents', 0) / 100:,.2f}")
    if 'negotiation' in r: lines += ['', negotiation_summary(r['negotiation'])]
    return '\n'.join(lines)


def negotiation_summary(n):
    if n.get('status') == 'skipped': return 'Negotiation skipped: ' + (n.get('reason') or 'no reason given')
    lines = [f"Negotiation {n.get('status')} (budget ${n.get('budget_usd') or 0:,.2f})"]
    best = n.get('best_offer')
    if best:
        lines.append(f"BEST DEAL: ${best['price_usd']:,.2f} from {best['dealer']} "
                     f"(listed ${best['listing_usd']:,.2f}, you save ${best['savings_usd']:,.2f})")
        for o in (n.get('offers') or [])[1:]: lines.append(f"  also: ${o['price_usd']:,.2f} from {o['dealer']}")
        lines.append('Offers expire in about 10 minutes. Accept on the website:')
    else:
        lines.append('No dealer made a valid offer. Details on the website:')
    if n.get('deal_room_url'): lines.append('  ' + n['deal_room_url'])
    return '\n'.join(lines)


def main(argv):
    as_json, negotiate, budget, args = False, False, None, []
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == '--json': as_json = True
        elif a == '--negotiate': negotiate = True
        elif a == '--budget':
            try: budget = float(rest.pop(0))
            except (IndexError, ValueError): print('--budget needs a number in USD', file=sys.stderr); return 1
        else: args.append(a)
    if budget is not None and not negotiate: print('--budget only applies with --negotiate', file=sys.stderr); return 1
    url, key = os.environ.get('MIVO_URL'), os.environ.get('MIVO_DEVICE_KEY')
    if len(args) != 1: print(__doc__, file=sys.stderr); return 1
    if not url or not key: print('Set MIVO_URL and MIVO_DEVICE_KEY (e.g. source ~/.config/mivo/env)', file=sys.stderr); return 1
    try:
        path = capture() if args[0] == '--capture' else args[0]
        if not os.path.isfile(path): raise Fatal(f'No such file: {path}', 1)
        if negotiate: print('Identifying and negotiating; this takes 2-4 minutes…', file=sys.stderr)
        result = send(path, url, key, negotiate, budget)
    except Fatal as e:
        print(e, file=sys.stderr); return e.code
    print(json.dumps(result, indent=2, ensure_ascii=False) if as_json else summary(result))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
PYEOF
chmod +x ~/mivo/mivo_identify.py
```

## Step 5: Use it

```sh
source ~/.config/mivo/env

python3 ~/mivo/mivo_identify.py --capture          # take a photo and identify it
python3 ~/mivo/mivo_identify.py ~/test.jpg         # identify an existing photo
python3 ~/mivo/mivo_identify.py --capture --json   # raw JSON reply (for other programs)

python3 ~/mivo/mivo_identify.py --capture --negotiate              # identify AND haggle for the best price
python3 ~/mivo/mivo_identify.py --capture --negotiate --budget 750 # same, with your budget in USD
```

Example output:
```
Apple iPhone 15 Pro
Apple · iPhone 15 Pro · Smartphone
A pre-owned Apple iPhone 15 Pro in Natural Titanium, featuring 128GB of storage. ...
  • 128GB storage
  • Natural Titanium finish
Price: $800–$850 (estimate)
Where to buy: Apple Store, Authorized Apple Resellers, Second-hand electronics retailers
Confidence: 100%  ·  no web search used; prices may be out of date
```
A reply takes about 15–30 seconds.

### Negotiating (`--negotiate`)
Mivo invites three demo dealers selling the product, its AI haggles with them, and the best deal comes back to the Pi. **This takes 2–4 minutes.**
```
Negotiation completed (budget $728.64)
BEST DEAL: $761.94 from Urban Gadget Hub · Demo (listed $857.22, you save $95.28)
  also: $782.26 from BrightBuy Store · Demo
  also: $806.13 from Circuit Corner · Demo
Offers expire in about 10 minutes. Accept on the website:
  https://mivo-harshithnair0307-6911s-projects.vercel.app/deal-room?id=…
```
The full conversation appears on the website under **My Deals**, for the buyer account the Mivo owner set as `DEVICE_BUYER_EMAIL`. Log in as that account to accept the deal; nothing is bought automatically. Dealers are demo merchants, not real shops.

**Tips for good results:** the product should fill most of the frame, in good light, with any label or model number visible.

---

## What the server sends back (`--json`)

| Field | Meaning |
|---|---|
| `identified` | `false` = nothing recognised; retake the photo |
| `name`, `brand`, `model`, `category`, `description` | text, or `null` if unknown |
| `key_features`, `where_to_buy` | lists of text (may be empty) |
| `price_range_usd` | `{"low": …, "high": …}`, an estimate, not a quote |
| `confidence` | 0 to 1 |
| `web_search` | `true` = checked with live web search; `false` = AI knowledge only, prices may be out of date |
| `sources` | web pages used (only when `web_search` is true) |
| `catalog_matches` | matching products sold on Mivo (`price_cents` ÷ 100 = dollars) |
| `negotiation` | only with `--negotiate`: `status`, `best_offer` (`dealer`, `price_usd`, `listing_usd`, `savings_usd`), all `offers`, `deal_room_url` |

## If something goes wrong

| Message | Fix |
|---|---|
| `Set MIVO_URL and MIVO_DEVICE_KEY` | Run `source ~/.config/mivo/env` first |
| `Device key rejected (401)` | Wrong key in `~/.config/mivo/env` |
| `Request rejected (413)` | Photo over 4 MB: use a lower resolution |
| `Request rejected (415)` | File isn't a real JPEG/PNG/WebP |
| `Request rejected (422)` | `--budget` must be between 0.01 and 100000 |
| `Busy (429)` | Two negotiations already running; wait a few minutes |
| `Negotiation skipped: …` | No product recognised, or no price estimate: retake the photo |
| `Server not configured (503)` | Server-side setting missing (with `--negotiate`, usually `DEVICE_BUYER_EMAIL`): tell the Mivo owner |
| `Server error (502)` / `Network error` | The script already retried twice; check internet, try again later |
| `No camera tool found` | Install `rpicam-apps` (`sudo apt install -y rpicam-apps`) or `fswebcam` |
| `Camera capture failed` | Check the camera cable; run `rpicam-hello --list-cameras` |

Exit codes for automation: `0` success, `1` setup problem, `2` rejected (key or image), `3` server or network failure.

---

## Optional: a push-button that scans

Wire a button between **GPIO17 (pin 11)** and **GND (pin 9)**, then:

```sh
cat > ~/mivo/button.py <<'PYEOF'
#!/usr/bin/env python3
"""Press the button: take a photo, identify it, print the result."""
import subprocess, sys
from signal import pause
from gpiozero import Button

def scan():
    print('Scanning…', flush=True)
    subprocess.run([sys.executable, '/home/' + __import__('getpass').getuser() + '/mivo/mivo_identify.py', '--capture'])

button = Button(17, bounce_time=0.3)
button.when_pressed = scan
print('Ready: press the button to scan.', flush=True)
pause()
PYEOF
source ~/.config/mivo/env && python3 ~/mivo/button.py
```
(`gpiozero` comes with Raspberry Pi OS. If it's missing, run `sudo apt install -y python3-gpiozero`.)

## Optional: start the button scanner automatically on boot

```sh
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/mivo-button.service <<'UNIT'
[Unit]
Description=Mivo button scanner
After=network-online.target

[Service]
ExecStart=/bin/bash -c 'source %h/.config/mivo/env && exec python3 %h/mivo/button.py'
Restart=on-failure

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now mivo-button.service
sudo loginctl enable-linger "$USER"     # keep it running without being logged in
journalctl --user -u mivo-button -f     # watch the results
```
