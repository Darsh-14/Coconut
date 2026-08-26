"""API endpoints. Implements CLAUDE.md Section 8 exactly.

    GET  /disputes                       queue with computed status
    GET  /disputes/{dispute_id}          dispute + latest decision + audit trail
    POST /disputes/{dispute_id}/decide   run the pipeline, persist and return a Decision
    POST /disputes/{dispute_id}/approve  record human approval, apply Section 7 handling
    POST /evaluate                       run the pipeline over the held-out set

The safety-critical endpoint is /approve. Section 2's second hard constraint is that the
system never submits to Razorpay's live dispute workflow, and Section 7 specifies what to
do instead: build the exact payload we WOULD send, store it on the audit entry, and mark
submitted_to_razorpay so the UI can label it "would submit to Razorpay". The actual network
call is blocked one layer down in razorpay_client._dispute_call(), which refuses any
synthetic dispute id. Both layers are tested.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db.database import get_session
from app.db.models import AuditLogRow, DecisionRow, DisputeRow
from app.models.schemas import (
    ApproveRequest,
    AuditLogEntry,
    Decision,
    DisputeDetail,
    DisputeSummary,
    EvalMetrics,
)
from app.services.decision_aggregator import aggregate, build_decision
from app.services.packet_generator import generate_packet
from app.services.razorpay_client import (
    build_contest_payload,
    is_placeholder_payment_id,
)
from app.services.verification_engine import get_verification_engine

logger = logging.getLogger("recourse.api")

router = APIRouter()


# --- helpers ----------------------------------------------------------------------------


def _load_dispute(session: Session, dispute_id: str) -> DisputeRow:
    row = session.scalars(
        select(DisputeRow)
        .options(selectinload(DisputeRow.decisions), selectinload(DisputeRow.audit_entries))
        .where(DisputeRow.dispute_id == dispute_id)
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown dispute {dispute_id}"
        )
    return row


# --- endpoints --------------------------------------------------------------------------


@router.get("/disputes", response_model=list[DisputeSummary], tags=["disputes"])
def list_disputes(
    session: Session = Depends(get_session),
    dispute_status: Optional[str] = Query(
        None, alias="status", description="Filter by computed status."
    ),
    limit: int = Query(500, ge=1, le=1000),
) -> list[DisputeSummary]:
    """The dispute queue, most urgent first."""
    rows = session.scalars(
        select(DisputeRow)
        .options(selectinload(DisputeRow.decisions), selectinload(DisputeRow.audit_entries))
        .order_by(DisputeRow.respond_by)
    ).all()

    summaries = [
        DisputeSummary(
            dispute_id=row.dispute_id,
            phase=row.phase,
            reason_code=row.reason_code,
            amount=row.amount,
            currency=row.currency,
            respond_by=row.respond_by,
            status=row.computed_status(),
            payment_id=row.payment_id,
            payment_is_real=not is_placeholder_payment_id(row.payment_id),
        )
        for row in rows
    ]
    if dispute_status:
        summaries = [s for s in summaries if s.status == dispute_status]
    return summaries[:limit]


@router.get("/disputes/{dispute_id}", response_model=DisputeDetail, tags=["disputes"])
def get_dispute(dispute_id: str, session: Session = Depends(get_session)) -> DisputeDetail:
    """Full dispute, its latest decision (nullable) and its audit trail."""
    row = _load_dispute(session, dispute_id)
    latest = row.latest_decision
    return DisputeDetail(
        dispute=row.to_schema(),
        latest_decision=latest.to_schema() if latest else None,
        decision_rationale=latest.rationale if latest else None,
        audit_log=[entry.to_schema() for entry in row.audit_entries],
        status=row.computed_status(),
        payment_is_real=not is_placeholder_payment_id(row.payment_id),
    )


@router.post(
    "/disputes/{dispute_id}/decide",
    response_model=Decision,
    tags=["disputes"],
)
def decide(dispute_id: str, session: Session = Depends(get_session)) -> Decision:
    """Run the verification engine and aggregator, persist the decision, return it.

    Re-running appends a new decision rather than overwriting: the audit trail should show
    that a case was re-assessed, not silently rewrite history.
    """
    row = _load_dispute(session, dispute_id)
    evidence = row.evidence_items()

    engine = get_verification_engine()
    verdicts = engine.verify_bundle(row.claim_text, evidence, row.reason_code)
    result = aggregate(verdicts, evidence)

    # Only CONTEST decisions get a drafted representment (Section 12).
    packet = None
    if result.recommendation == "CONTEST":
        packet = generate_packet(
            dispute=row.to_schema(), verdicts=verdicts, rationale=result.rationale
        )

    decision = build_decision(
        dispute_id=dispute_id,
        verdicts=verdicts,
        evidence_bundle=evidence,
        drafted_packet=packet,
    )

    session.add(DecisionRow.from_schema(decision, rationale=result.rationale))
    session.commit()

    logger.info(
        "decided %s -> %s (confidence %.3f)",
        dispute_id,
        decision.recommendation,
        decision.confidence,
    )
    return decision


@router.post(
    "/disputes/{dispute_id}/approve",
    response_model=AuditLogEntry,
    tags=["disputes"],
)
def approve(
    dispute_id: str,
    body: ApproveRequest,
    session: Session = Depends(get_session),
) -> AuditLogEntry:
    """Record a human's approval decision.

    Section 7: on approval of a CONTEST we build the exact payload we would send to
    Razorpay, store it, and set submitted_to_razorpay -- but do NOT make the call, because
    the dispute does not exist on Razorpay's side. The UI labels this "would submit to
    Razorpay". Section 2's constraint that a human must approve is why this endpoint
    exists at all: nothing else in the system can set these flags.
    """
    row = _load_dispute(session, dispute_id)
    latest = row.latest_decision
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{dispute_id} has no decision yet; POST /disputes/{dispute_id}/decide first.",
        )

    entry = AuditLogRow(
        dispute_id=dispute_id,
        decision_id=latest.id,
        approved_by_human=body.approved,
        approved_at=datetime.now(timezone.utc) if body.approved else None,
        edited_packet=body.edited_packet,
        submitted_to_razorpay=False,
    )

    if not body.approved:
        entry.note = "Human rejected the recommendation. Nothing was prepared for submission."
        session.add(entry)
        session.commit()
        logger.info("approval REJECTED for %s", dispute_id)
        return entry.to_schema()

    if latest.recommendation == "CONTEST":
        packet_text = body.edited_packet or latest.drafted_packet or ""
        evidence_refs = [
            e.source_ref
            for e in row.evidence_items()
            if e.source_ref
        ]
        entry.would_be_razorpay_payload = build_contest_payload(
            dispute_id=dispute_id,
            amount_paise=row.amount,
            packet_text=packet_text,
            evidence_refs=evidence_refs,
        )
        # True means "prepared and logged as if submitted", never "sent". The network call
        # is blocked in razorpay_client._dispute_call() for any synthetic dispute id.
        entry.submitted_to_razorpay = True
        entry.note = (
            "Representment prepared and logged. NOT transmitted: this dispute is "
            "synthetic and does not exist on Razorpay's side (CLAUDE.md Section 7)."
        )
    else:
        entry.note = (
            f"Human approved the {latest.recommendation} recommendation. No representment "
            f"is prepared for a non-CONTEST outcome."
        )

    session.add(entry)
    session.commit()
    logger.info(
        "approval RECORDED for %s (%s), would_be_payload=%s",
        dispute_id,
        latest.recommendation,
        bool(entry.would_be_razorpay_payload),
    )
    return entry.to_schema()


@router.post("/evaluate", response_model=EvalMetrics, tags=["evaluation"])
def evaluate(
    limit: Optional[int] = Query(None, ge=1, description="Evaluate only the first N records.")
) -> EvalMetrics:
    """Run the full pipeline over eval/held_out_set.json and return Section 11's metrics.

    Reads the held-out file directly and never touches the database: those records are
    deliberately not seeded into the queue (Section 9).

    This is slow -- it runs NLI inference over the whole held-out set -- so it is a POST
    that the dashboard triggers explicitly rather than something computed on page load.
    """
    from eval.run_evaluation import run_evaluation

    settings = get_settings()
    records = None
    if limit:
        from eval.run_evaluation import load_held_out

        records = load_held_out()[:limit]

    metrics = run_evaluation(
        records=records,
        engine=get_verification_engine(),
        representment_cost_inr=settings.assumed_representment_cost_inr,
    )
    logger.info(
        "evaluated %s records: precision=%.3f recall=%.3f f1=%.3f coverage=%.3f",
        metrics.n_evaluated,
        metrics.precision,
        metrics.recall,
        metrics.f1,
        metrics.coverage,
    )
    return metrics


__all__ = ["router"]
