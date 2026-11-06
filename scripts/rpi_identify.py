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
