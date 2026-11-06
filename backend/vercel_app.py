"""Vercel entrypoint for the FastAPI backend.

The Vercel service root is backend/, so this directory is deployed flat. Register it
as the `backend` package so the app's absolute `backend.*` imports keep working, then
strip the public /api prefix that Vercel Services forwards unchanged.
"""
import sys
import types
from pathlib import Path

if 'backend' not in sys.modules:
    package = types.ModuleType('backend')
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules['backend'] = package

from backend.api.main import app as api  # noqa: E402

PREFIX = '/api'

async def app(scope, receive, send):
    if scope['type'] in ('http', 'websocket'):
        path = scope.get('path', '')
        if path == PREFIX or path.startswith(PREFIX + '/'):
            scope = dict(scope, path=path[len(PREFIX):] or '/', raw_path=None, root_path='')
    await api(scope, receive, send)
