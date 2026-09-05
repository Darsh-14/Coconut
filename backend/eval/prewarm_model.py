"""Download/cache the pinned NLI weights and run one prediction; never fit a model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.verification_engine import get_verification_engine, MODEL_VERSION  # noqa: E402

if __name__ == '__main__':
    engine = get_verification_engine()
    engine.model.predict([('The parcel arrived.', 'Delivery is confirmed.')])
    print(f'PASS: cached weights loaded and inference completed: {MODEL_VERSION}')
    print('Server startup loads this cache into memory; wait for /api/ready before presenting.')
