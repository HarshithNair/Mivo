"""0G Compute Router client. Every call returns the router's own request metadata so each
negotiation decision can be traced to a real 0G request (X-Request-ID / x_0g_trace)."""
import asyncio
import json
import time
import httpx
from backend.integrations.zerog.config import zerog_settings as zs

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ZeroGError(Exception):
    def __init__(self, message, meta=None):
        super().__init__(message)
        self.meta = meta or {}


def parse_json(text):
    """Models sometimes wrap JSON in prose or code fences; take the outermost object."""
    start, end = (text or '').find('{'), (text or '').rfind('}')
    if start == -1 or end <= start: raise ValueError('model did not return a JSON object')
    return json.loads(text[start:end + 1])


async def chat_json(messages, client_request_id=None, max_tokens=None):
    """One JSON-mode chat completion on 0G. Returns (parsed_json, meta). Raises ZeroGError."""
    if not zs.zerog_api_key: raise ZeroGError('ZEROG_API_KEY is not set')
    body = {'model': zs.zerog_model, 'messages': messages, 'temperature': 0.2,
            'max_tokens': max_tokens or zs.zerog_max_tokens, 'response_format': {'type': 'json_object'}}
    headers = {'Authorization': f'Bearer {zs.zerog_api_key}', 'Content-Type': 'application/json'}
    if client_request_id: headers['X-Client-Request-Id'] = client_request_id
    last = None
    for attempt in range(zs.zerog_retries + 1):
        started = time.monotonic()
        meta = {'provider': '0g', 'router': zs.zerog_router_url, 'model': zs.zerog_model, 'attempts': attempt + 1}
        try:
            async with httpx.AsyncClient(timeout=zs.zerog_timeout) as http:
                r = await http.post(zs.zerog_router_url.rstrip('/') + '/chat/completions', json=body, headers=headers)
            meta['latency_ms'] = round((time.monotonic() - started) * 1000)
            meta['http_status'] = r.status_code
            meta['request_id'] = r.headers.get('x-request-id')
            meta['provider_address'] = r.headers.get('x-provider')
            data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            trace = data.get('x_0g_trace') or {}
            meta['request_id'] = trace.get('request_id') or meta['request_id']
            meta['provider_address'] = trace.get('provider') or meta['provider_address']
            meta['provider_identity'] = trace.get('provider_identity')
            meta['tee_verified'] = trace.get('tee_verified')
            if r.status_code != 200:
                err = (data.get('error') or {}).get('message') if isinstance(data.get('error'), dict) else data.get('error')
                last = ZeroGError(f'0G router HTTP {r.status_code}: {err or r.text[:200]}', meta)
                if r.status_code in RETRY_STATUS and attempt < zs.zerog_retries: await asyncio.sleep(1.5 * (attempt + 1)); continue
                raise last
            meta['model'] = data.get('model') or meta['model']
            meta['response_id'] = data.get('id')
            meta['usage'] = data.get('usage')
            content = ((data.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
            try: return parse_json(content), meta
            except (ValueError, json.JSONDecodeError) as exc:
                meta['raw'] = content[:300]
                last = ZeroGError(f'invalid model output: {exc}', meta)
        except httpx.TimeoutException:
            last = ZeroGError(f'0G router timed out after {zs.zerog_timeout}s', {**meta, 'latency_ms': round((time.monotonic() - started) * 1000)})
        except httpx.HTTPError as exc:
            last = ZeroGError(f'0G router unreachable: {type(exc).__name__}', meta)
        if attempt < zs.zerog_retries: await asyncio.sleep(1.5 * (attempt + 1))
    raise last


async def list_models():
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.get(zs.zerog_router_url.rstrip('/') + '/models')
        r.raise_for_status()
        data = r.json()
    return data.get('data', data) if isinstance(data, dict) else data
