"""Add and assess four presentation cases in the configured demo database. No training.

Uses working-set score cache to nominate cases, then verifies each using real inference.
No Razorpay objects are created. --verify-backing performs a read-only remote payment check.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Demo preparation does not require paid LLM drafting.
os.environ['LLM_PROVIDER'] = 'none'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-backing', action='store_true')
    args = parser.parse_args()
    from sqlalchemy import select
    from app.db.database import init_db, SessionLocal
    from app.db.models import DisputeRow
    from app.models.schemas import Dispute
    from app.services.conformal_calibrator import bootstrap_from_cache, load_scores, get_active_calibrated_threshold
    from app.services.synthetic_win_gate import load_synthetic_win_model, predict_probability
    from app.services.npci_rules import NPCI_RULES
    from app.api.routes import decide

    init_db()
    bootstrap_from_cache()
    cache = load_scores()
    model = load_synthetic_win_model()
    threshold = get_active_calibrated_threshold()
    if cache is None or model is None or threshold is None:
        raise RuntimeError('Model artifact or calibration unavailable; run the readiness checks first.')
    records = {r.dispute_id: r for r in (
        Dispute.model_validate(v) for v in json.loads((ROOT / 'data/synthetic_disputes.json').read_text(encoding='utf-8'))
    )}
    selected = {}
    for row in cache['calibration']:
        record = records[row['dispute_id']]
        if record.rail != 'card':
            continue
        if row['max_contradict'] is not None and row['max_contradict'] >= threshold:
            recommendation = 'ACCEPT'
        elif row['score'] is not None and row['score'] >= threshold and predict_probability(record, model) >= model.threshold:
            recommendation = 'CONTEST'
        else:
            recommendation = 'NEEDS_HUMAN_REVIEW'
        selected.setdefault(recommendation, record)
    if len(selected) != 3:
        raise RuntimeError(f'Working set has no candidate for all outcomes: {sorted(selected)}')
    now = datetime.now(timezone.utc)
    expected = {}
    with SessionLocal() as session:
        for recommendation, source in selected.items():
            record_id = 'disp_synthetic_demo_' + recommendation.lower()
            expected[record_id] = recommendation
            if session.get(DisputeRow, record_id) is None:
                clone = source.model_copy(update={
                    'dispute_id': record_id, 'payment_id': 'pay_PENDING_' + record_id,
                    'raised_at': now, 'respond_by': now + timedelta(days=14),
                    'ground_truth_label': None,
                })
                session.add(DisputeRow.from_schema(clone))
        # The final chargeback follows the configured payer-payee cap worth of history.
        source = selected['NEEDS_HUMAN_REVIEW']
        cap = NPCI_RULES['cap_per_payer_payee_30d']
        for index in range(cap + 1):
            record_id = f'disp_synthetic_demo_upi_{index}'
            if session.get(DisputeRow, record_id) is None:
                clone = source.model_copy(update={
                    'dispute_id': record_id, 'payment_id': 'pay_PENDING_' + record_id,
                    'phase': 'chargeback', 'rail': 'upi', 'payer_ref': 'demo_payer_cap_scenario',
                    'raised_at': now - timedelta(hours=cap-index),
                    'respond_by': now + timedelta(days=14), 'ground_truth_label': None,
                })
                session.add(DisputeRow.from_schema(clone))
        expected[record_id] = 'NO_ACTION_NEEDED'
        session.commit()
        failures = []
        for record_id, recommendation in expected.items():
            print(f'Assessing {record_id} ...', flush=True)
            try:
                result = decide(record_id, session)
                passed = result.recommendation == recommendation
                print(f'{"PASS" if passed else "FAIL"}: expected {recommendation}, observed {result.recommendation}; /app/disputes/{record_id}', flush=True)
                if not passed:
                    failures.append(record_id)
            except Exception as exc:
                failures.append(record_id)
                print(f'FAIL {record_id}: {exc}', flush=True)
        backing = False
        if args.verify_backing:
            from app.services.razorpay_client import get_razorpay_client, is_placeholder_payment_id
            for row in session.scalars(select(DisputeRow)).all():
                if is_placeholder_payment_id(row.payment_id):
                    continue
                try:
                    payment = get_razorpay_client().fetch_payment(row.payment_id)
                    if payment and payment.get('id') == row.payment_id and payment.get('status') in {'authorized', 'captured'} and payment.get('amount') == row.amount and payment.get('currency') == row.currency:
                        backing = True
                        print(f'PASS: remote Razorpay test payment verified for /app/disputes/{row.dispute_id}')
                        break
                except Exception:
                    print(f'Payment verification failed for {row.dispute_id}; check credentials and account access.')
            if not backing:
                print('PENDING: complete test Checkout on a case, then repeat --verify-backing.')
        print('Demo fixtures do not change training or held-out files.')
        return 1 if failures or (args.verify_backing and not backing) else 0


if __name__ == '__main__':
    raise SystemExit(main())
