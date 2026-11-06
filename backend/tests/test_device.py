"""Raspberry Pi image ingress: bearer auth, image validation, Gemini result passthrough."""
import pytest
from fastapi.testclient import TestClient
from backend.config import settings
from backend.schemas import Identification
from backend.api import device
from backend.api.main import app
from test_core import database

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 100
KEY = 'test-device-key'


@pytest.fixture
def pi(monkeypatch):
    monkeypatch.setattr(settings, 'device_api_key', KEY)
    monkeypatch.setattr(settings, 'gemini_api_key', 'test')
    calls = []
    async def fake(image, mime):
        calls.append((image, mime))
        return Identification(identified=True, name='Studio ANC Headphones', brand='Mivo', confidence=0.9), [{'title': 'Example', 'url': 'https://example.com'}]
    monkeypatch.setattr(device, 'identify_product', fake)
    with TestClient(app) as c:  # no Origin header, like a real device
        c.calls = calls; yield c


def post(c, body=JPEG, mime='image/jpeg', key=KEY):
    return c.post('/device/identify', content=body, headers={'content-type': mime, 'authorization': f'Bearer {key}'})


def test_identifies_and_matches_catalog(pi):
    r = post(pi); assert r.status_code == 200, r.text
    data = r.json()
    assert data['name'] == 'Studio ANC Headphones' and data['sources'][0]['url'] == 'https://example.com'
    assert data['catalog_matches'] and all('floor_cents' not in m for m in data['catalog_matches'])
    assert pi.calls == [(JPEG, 'image/jpeg')]


def test_rejects_bad_key(pi):
    assert post(pi, key='wrong').status_code == 401
    assert pi.post('/device/identify', content=JPEG, headers={'content-type': 'image/jpeg'}).status_code == 401


def test_disabled_without_key(pi, monkeypatch):
    monkeypatch.setattr(settings, 'device_api_key', '')
    assert post(pi).status_code == 503


@pytest.mark.parametrize('body,mime', [(JPEG, 'text/plain'), (b'not an image', 'image/jpeg'), (b'RIFF0000WAVE', 'image/webp')])
def test_rejects_non_images(pi, body, mime):
    assert post(pi, body, mime).status_code == 415 and not pi.calls


def test_rejects_oversized(pi):
    assert post(pi, JPEG + b'0' * device.MAX_IMAGE_BYTES).status_code == 413 and not pi.calls


def test_parses_fenced_json():
    from backend.agents.gemini import parse_json_object
    assert parse_json_object('```json\n{"identified": true, "name": "X"}\n```')['name'] == 'X'
    with pytest.raises(ValueError): parse_json_object('no product here')


def test_identification_trims_untrusted_output():
    i = Identification(identified=True, name='n' * 500, key_features=['f'] * 50, confidence=7)
    assert len(i.name) == 120 and len(i.key_features) == 10 and i.confidence == 1.0
