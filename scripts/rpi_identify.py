#!/usr/bin/env python3
"""Send a photo from a Raspberry Pi to Mivo and print the product details it returns.

Standard library only. Usage:
    export MIVO_URL=https://your-app.vercel.app
    export MIVO_DEVICE_KEY=...            # same value as DEVICE_API_KEY on Vercel
    python3 rpi_identify.py photo.jpg     # or: --capture to take a photo with rpicam-still
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


def capture():
    path = os.path.join(tempfile.gettempdir(), 'mivo-capture.jpg')
    # 1280px wide JPEG keeps uploads well under the 4 MB limit.
    subprocess.run(['rpicam-still', '-n', '-t', '1000', '--width', '1280', '--height', '960', '-o', path], check=True)
    return path


def identify(path, url, key):
    mime = TYPES.get(os.path.splitext(path)[1].lower())
    if not mime: sys.exit('Use a .jpg, .png or .webp image')
    with open(path, 'rb') as f: body = f.read()
    request = urllib.request.Request(url.rstrip('/') + '/api/device/identify', data=body, method='POST',
                                     headers={'Content-Type': mime, 'Authorization': 'Bearer ' + key})
    try:
        with urllib.request.urlopen(request, timeout=120) as response: return json.load(response)
    except urllib.error.HTTPError as e:
        sys.exit(f'HTTP {e.code}: {e.read().decode(errors="replace")}')


if __name__ == '__main__':
    url, key = os.environ.get('MIVO_URL'), os.environ.get('MIVO_DEVICE_KEY')
    if not url or not key or len(sys.argv) != 2: sys.exit(__doc__)
    print(json.dumps(identify(capture() if sys.argv[1] == '--capture' else sys.argv[1], url, key), indent=2))
