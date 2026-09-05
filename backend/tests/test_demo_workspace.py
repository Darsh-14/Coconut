"""Exercise the demo in its own process, as required by its isolation boundary."""
import os
import subprocess
import sys
from pathlib import Path


def test_demo_isolates_credentials_database_and_reset(tmp_path):
    merchant = tmp_path / 'merchant.db'
    merchant.write_bytes(b'merchant data must not be opened or reset')
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{merchant.as_posix()}',
           'RAZORPAY_KEY_ID': 'rzp_test_merchant', 'RAZORPAY_KEY_SECRET': 'merchant-secret',
           'COCONUT_SKIP_WARMUP': '1'}
    result = subprocess.run([sys.executable, '-c', '''
from fastapi.testclient import TestClient
from app.demo import app
from app.config import get_settings
from app.db.database import SessionLocal
from app.db.models import DisputeRow
from app.services.conformal_calibrator import active_state, DEFAULT_ALPHA
settings = get_settings()
assert settings.razorpay_key_secret == 'isolated_demo_only'
assert settings.resolve_llm_provider() == 'none'
with TestClient(app) as client:
    assert client.get('/api/workspace').json() == {'demo': True}
    scenarios = client.get('/api/demo/scenarios').json()['scenarios']
    assert len(scenarios) == 4
    before = client.get('/api/disputes').json()
    assert len(before) >= 4
    first = scenarios[0]['id']
    with SessionLocal.begin() as session:
        row = session.get(DisputeRow, first)
        row.payment_id = 'pay_modified'
    assert client.post(f'/api/disputes/{first}/backing-order').status_code == 403
    assert client.post('/api/webhooks/razorpay').status_code == 403
    assert client.post('/api/calibrate', json={'alpha': 0.1, 'delta': 0.1}).status_code == 200
    assert client.post('/api/demo/reset').status_code == 200
    assert active_state()['alpha'] == DEFAULT_ALPHA
    after = client.get('/api/disputes').json()
    assert {r['dispute_id'] for r in before} == {r['dispute_id'] for r in after}
    assert all(r['payment_id'] != 'pay_modified' for r in after)
    assert all(r['recommendation'] is None for r in after)
'''], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert merchant.read_bytes() == b'merchant data must not be opened or reset'


def test_normal_app_has_no_demo_reset():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.demo_cases import reset_demo
    import pytest
    with pytest.raises(RuntimeError, match='isolated demo'):
        reset_demo()
    client = TestClient(app)
    assert client.get('/workspace').json() == {'demo': False}
    assert client.post('/demo/reset').status_code == 404
