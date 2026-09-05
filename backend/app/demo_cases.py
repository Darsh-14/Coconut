"""Prepared inputs from the working set; decisions always use the normal engine."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.database import Base, SessionLocal
from app.db.models import DisputeRow
from app.db.seed import load_working_set
from app.services.conformal_calibrator import DEFAULT_ALPHA, DEFAULT_DELTA, bootstrap_from_cache, load_scores, get_active_calibrated_threshold
from app.services.synthetic_win_gate import load_synthetic_win_model, predict_probability
from app.services.npci_rules import NPCI_RULES


def scenarios():
    return [
        {'id': 'disp_synthetic_demo_contest', 'label': 'Contest'},
        {'id': 'disp_synthetic_demo_accept', 'label': 'Accept'},
        {'id': 'disp_synthetic_demo_review', 'label': 'Human review'},
        {'id': f"disp_synthetic_demo_upi_{NPCI_RULES['cap_per_payer_payee_30d']}", 'label': 'UPI limit'},
    ]


def prepared_cases():
    cache = load_scores()
    model = load_synthetic_win_model()
    threshold = get_active_calibrated_threshold()
    if cache is None or model is None or threshold is None:
        raise RuntimeError('Demo requires the committed model and calibration cache')
    records = {r.dispute_id: r for r in load_working_set()}
    selected = {}
    for score in cache['calibration']:
        record = records[score['dispute_id']]
        if record.rail != 'card':
            continue
        if score['max_contradict'] is not None and score['max_contradict'] >= threshold:
            outcome = 'accept'
        elif score['score'] is not None and score['score'] >= threshold and predict_probability(record, model) >= model.threshold:
            outcome = 'contest'
        else:
            outcome = 'review'
        selected.setdefault(outcome, record)
    if set(selected) != {'contest', 'accept', 'review'}:
        raise RuntimeError('Demo working set lacks the required scenarios')
    now = datetime.now(timezone.utc)
    cases = []
    def clone(source, name, **extra):
        return source.model_copy(update={
            'dispute_id': f'disp_synthetic_demo_{name}',
            'payment_id': f'pay_PENDING_demo_{name}',
            'raised_at': now, 'respond_by': now + timedelta(days=7),
            'ground_truth_label': None, **extra,
        })
    for outcome, source in selected.items():
        cases.append(clone(source, outcome))
    cap = NPCI_RULES['cap_per_payer_payee_30d']
    for index in range(cap + 1):
        cases.append(clone(selected['review'], f'upi_{index}', rail='upi', phase='chargeback',
                           payer_ref='demo_payer_cap_scenario', raised_at=now - timedelta(hours=cap-index)))
    return cases


def reset_demo():
    # Only the separate demo entrypoint may authorize a destructive reset.
    from app.main import app
    if not getattr(app.state, 'demo', False):
        raise RuntimeError('Reset is available only in the isolated demo process')
    bootstrap_from_cache(DEFAULT_ALPHA, DEFAULT_DELTA)
    cases = prepared_cases()  # Validate before deleting any previous session.
    with SessionLocal.begin() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(delete(table))
        session.add_all(DisputeRow.from_schema(case) for case in cases)
