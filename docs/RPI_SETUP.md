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
import urllib.request

TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
MAX_BYTES = 4 * 1024 * 1024
RETRY_WAITS = (15, 30)  # for 502 / network errors: two retries
TIMEOUT = 120


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


def send(path, url, key):
    mime = TYPES.get(os.path.splitext(path)[1].lower())
    if not mime: raise Fatal('Use a .jpg, .jpeg, .png or .webp image', 1)
    with open(path, 'rb') as f: body = f.read()
    if len(body) > MAX_BYTES: raise Fatal(f'Image is {len(body) // 1024} KB; it must be 4 MB or smaller', 2)
    request = urllib.request.Request(url.rstrip('/') + '/api/device/identify', data=body, method='POST',
                                     headers={'Content-Type': mime, 'Authorization': 'Bearer ' + key, 'User-Agent': 'mivo-pi/1.0'})
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response: return json.load(response)
        except urllib.error.HTTPError as e:
            message = detail(e.read().decode(errors='replace'))
            if e.code == 401: raise Fatal('Device key rejected (401). Check MIVO_DEVICE_KEY.', 2)
            if e.code in (413, 415): raise Fatal(f'Image rejected ({e.code}): {message}', 2)
            if e.code == 503: raise Fatal(f'Server not configured (503): {message}', 3)
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
    return '\n'.join(lines)


def main(argv):
    as_json = '--json' in argv
    args = [a for a in argv if a != '--json']
    url, key = os.environ.get('MIVO_URL'), os.environ.get('MIVO_DEVICE_KEY')
    if len(args) != 1: print(__doc__, file=sys.stderr); return 1
    if not url or not key: print('Set MIVO_URL and MIVO_DEVICE_KEY (e.g. source ~/.config/mivo/env)', file=sys.stderr); return 1
    try:
        path = capture() if args[0] == '--capture' else args[0]
        if not os.path.isfile(path): raise Fatal(f'No such file: {path}', 1)
        result = send(path, url, key)
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

## If something goes wrong

| Message | Fix |
|---|---|
| `Set MIVO_URL and MIVO_DEVICE_KEY` | Run `source ~/.config/mivo/env` first |
| `Device key rejected (401)` | Wrong key in `~/.config/mivo/env` |
| `Image rejected (413)` | Photo over 4 MB: use a lower resolution |
| `Image rejected (415)` | File isn't a real JPEG/PNG/WebP |
| `Server not configured (503)` | Server-side problem: tell the Mivo owner |
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
