"""Isolated local demo: uvicorn app.demo:app --host 127.0.0.1 --port 8011.

Each process owns a fresh temporary database. Never imports merchant configuration before
replacing credentials and the database URL. Run a single worker for this local demo.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

if 'app.db.database' in sys.modules or 'app.main' in sys.modules:
    raise RuntimeError('Start the demo in its own process with app.demo:app')

_directory = tempfile.TemporaryDirectory(prefix='coconut-demo-')
os.environ.update({
    'DATABASE_URL': f"sqlite:///{(Path(_directory.name) / 'demo.db').as_posix()}",
    'RAZORPAY_KEY_ID': 'rzp_test_isolated_demo',
    'RAZORPAY_KEY_SECRET': 'isolated_demo_only',
    'RAZORPAY_WEBHOOK_SECRET': '',
    'LLM_PROVIDER': 'none',
})

from fastapi.responses import JSONResponse
from app.main import app as api_app
from app.demo_cases import reset_demo, scenarios
from app.services.automation import schedule_automatic_assessment

api_app.state.demo = True
_requests = asyncio.Lock()


@api_app.middleware('http')
async def isolate_demo_actions(request, call_next):
    # Serialize all demo requests so reset cannot race an assessment or approval.
    async with _requests:
        if 'backing-' in request.url.path or 'webhook' in request.url.path:
            return JSONResponse(status_code=403, content={'detail': 'Payments are disabled in the demo workspace.'})
        return await call_next(request)


@api_app.post('/demo/reset')
def reset():
    reset_demo()
    schedule_automatic_assessment()
    return {'scenarios': scenarios()}


@api_app.get('/demo/scenarios')
def list_scenarios():
    return {'scenarios': scenarios()}


from app.server import site as app
