"""API endpoints. Implements CLAUDE.md Section 8 exactly.

    GET  /disputes                       queue with computed status
    GET  /disputes/{dispute_id}          dispute + latest decision + audit trail
    GET  /disputes/{dispute_id}/urcs-forecast  NPCI cap forecast for a UPI dispute
    POST /disputes/{dispute_id}/decide   run the pipeline, persist and return a Decision
    POST /disputes/{dispute_id}/approve  record human approval, apply Section 7 handling
    POST /calibrate                      calibrate the threshold to a risk budget
    GET  /verify-guarantee               check the guarantee on the untouched test split
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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db.database import get_session
from app.db.models import AuditLogRow, CalibrationRow, DecisionRow, DisputeRow
from app.models.schemas import (
    ApproveRequest,
    CalibrateRequest,
    CalibrationResult,
    GuaranteeVerification,
    AuditLogEntry,
    Decision,
    Dispute,
    DisputeDetail,
    BackingOrder,
    BackingStatus,
    DisputeCreate,
    DisputeSummary,
    EvalMetrics,
    EvidenceAdd,
    EvidenceDocument,
    EvidenceItem,
    PacketDraft,
    URCSForecast,
)
from app.services.decision_aggregator import aggregate, build_decision
from app.services.evidence_documents import render_document
from app.services.conformal_calibrator import (
    active_state,
    calibrate_threshold,
    empirical_fp_rate,
    guarantee_statement,
    hoeffding_slack,
    load_scores,
    set_active_threshold,
    smallest_achievable_alpha,
)
from app.services.packet_generator import generate_packet
from app.services.urcs_forecaster import forecast_urcs_disposition
from app.services.razorpay_client import (
    MANUAL_DISPUTE_PREFIX,
    PENDING_PAYMENT_PREFIX,
    RazorpayError,
    build_contest_payload,
    get_razorpay_client,
    is_placeholder_payment_id,
)
from app.services.verification_engine import get_verification_engine

logger = logging.getLogger("recourse.api")

router = APIRouter()

# Line separator for the text exports below.
NEWLINE = "\n"


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


def _payer_history(session: Session, dispute: Dispute) -> list[Dispute]:
    """Every other UPI dispute from the same payer, for the NPCI cap counters.

    Narrowed in SQL rather than loading the queue: the counters only ever look at one
    payer, and this runs on every /decide.
    """
    if dispute.rail != "upi" or not dispute.payer_ref:
        return []
    rows = session.scalars(
        select(DisputeRow)
        .where(DisputeRow.payer_ref == dispute.payer_ref)
        .where(DisputeRow.dispute_id != dispute.dispute_id)
    ).all()
    return [r.to_schema() for r in rows]


# --- endpoints --------------------------------------------------------------------------


def _summarise(row: DisputeRow) -> DisputeSummary:
    """One queue row. `decisions` is eager-loaded, so the standing recommendation costs
    no extra query."""
    latest = row.latest_decision
    return DisputeSummary(
        dispute_id=row.dispute_id,
        phase=row.phase,
        reason_code=row.reason_code,
        amount=row.amount,
        currency=row.currency,
        respond_by=row.respond_by,
        status=row.computed_status(),
        payment_id=row.payment_id,
        payment_is_real=not is_placeholder_payment_id(row.payment_id),
        recommendation=latest.recommendation if latest else None,
        confidence=latest.confidence if latest else None,
        rail=row.rail or "card",
        urcs_reason_code=(
            (latest.urcs_forecast or {}).get("predicted_reason_code") if latest else None
        ),
    )


@router.get("/disputes", response_model=list[DisputeSummary], tags=["disputes"])
def list_disputes(
    response: Response,
    session: Session = Depends(get_session),
    dispute_status: Optional[str] = Query(
        None, alias="status", description="Filter by computed status."
    ),
    q: Optional[str] = Query(
        None,
        description="Match a dispute id, payment id, reason code or claim text.",
        max_length=120,
    ),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[DisputeSummary]:
    """The dispute queue, most urgent first.

    Search is pushed into SQL; `status` cannot be, because it is derived from a dispute's
    decisions and audit entries rather than stored. That is a deliberate trade -- deriving
    it keeps a single source of truth -- so it is applied after loading and the honest
    total is reported in X-Total-Count either way.

    The response stays a bare array, as Section 8 specifies. Paging metadata rides in
    headers rather than wrapping the body in an envelope, so the documented contract holds.
    """
    query = select(DisputeRow).options(
        selectinload(DisputeRow.decisions), selectinload(DisputeRow.audit_entries)
    )

    if q:
        # ESCAPE, because a merchant pasting an id containing _ (every id contains _)
        # would otherwise have it treated as a single-character wildcard.
        term = f"%{q.strip().replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%"
        query = query.where(
            or_(
                DisputeRow.dispute_id.ilike(term, escape=chr(92)),
                DisputeRow.payment_id.ilike(term, escape=chr(92)),
                DisputeRow.reason_code.ilike(term, escape=chr(92)),
                DisputeRow.claim_text.ilike(term, escape=chr(92)),
            )
        )

    # dispute_id is the tiebreaker, and it is load-bearing rather than tidiness: twelve
    # disputes share a respond_by, and ordering by a non-unique column alone leaves SQLite
    # free to return ties in a different order per query -- so paging could skip a row or
    # show it twice.
    rows = session.scalars(
        query.order_by(DisputeRow.respond_by, DisputeRow.dispute_id)
    ).all()
    summaries = [_summarise(row) for row in rows]
    if dispute_status:
        summaries = [item for item in summaries if item.status == dispute_status]

    response.headers["X-Total-Count"] = str(len(summaries))
    return summaries[offset : offset + limit]


@router.post(
    "/disputes",
    response_model=Dispute,
    status_code=status.HTTP_201_CREATED,
    tags=["disputes"],
)
def create_dispute(
    body: DisputeCreate, session: Session = Depends(get_session)
) -> Dispute:
    """File a dispute by hand.

    Until now the queue was a fixed seed loaded from a committed JSON file -- the app could
    only ever show what was shipped in it. This is the write path.

    The id is minted here rather than accepted from the caller: it keeps ids collision-free,
    and the disp_manual_ prefix makes provenance legible next to disp_synthetic_ at a
    glance. Neither can reach Razorpay's dispute workflow -- may_reach_razorpay() fails
    closed for every id, so a hand-filed dispute is no more transmissible than a seeded one.
    """
    now = datetime.now(timezone.utc)
    raised_at = body.raised_at or now
    # 14 days is a realistic issuer response window, used only when none is given.
    respond_by = body.respond_by or (raised_at + timedelta(days=14))

    latest = session.scalars(
        select(DisputeRow.dispute_id)
        .where(DisputeRow.dispute_id.like(f"{MANUAL_DISPUTE_PREFIX}%"))
        .order_by(DisputeRow.dispute_id.desc())
        .limit(1)
    ).first()
    next_n = (int(latest.rsplit("_", 1)[1]) + 1) if latest else 1
    dispute_id = f"{MANUAL_DISPUTE_PREFIX}{next_n:04d}"

    dispute = Dispute(
        dispute_id=dispute_id,
        payment_id=body.payment_id or f"{PENDING_PAYMENT_PREFIX}{next_n:04d}",
        phase=body.phase,
        reason_code=body.reason_code,
        claim_text=body.claim_text,
        amount=body.amount,
        currency=body.currency,
        raised_at=raised_at,
        respond_by=respond_by,
        evidence_bundle=body.evidence_bundle,
        # Never set from a request: it is evaluation-only, and a public write endpoint that
        # could set it would let whoever files a dispute shape the reported metrics.
        ground_truth_label=None,
        rail=body.rail,
        payer_ref=body.payer_ref,
    )

    session.add(DisputeRow.from_schema(dispute))
    session.commit()
    logger.info("filed %s (%s, %s paise)", dispute_id, body.reason_code, body.amount)
    return dispute


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
        decision_is_stale=bool(
            latest and (latest.evidence_revision or 0) != (row.evidence_revision or 0)
        ),
        edited_packet=latest.edited_packet if latest else None,
    )


def _bump_evidence(row: DisputeRow, bundle: list[EvidenceItem]) -> None:
    """Replace a dispute's evidence and mark every standing verdict as out of date.

    ClaimVerdict.evidence_index is a positional join. Changing the bundle without bumping
    the revision would leave the UI drawing a verdict about one item against a different
    one -- silently, and most misleadingly exactly when a merchant has just added the
    evidence they think will win the case.
    """
    row.evidence_bundle = [item.model_dump() for item in bundle]
    row.evidence_revision = (row.evidence_revision or 0) + 1


@router.post(
    "/disputes/{dispute_id}/evidence",
    response_model=Dispute,
    status_code=status.HTTP_201_CREATED,
    tags=["disputes"],
)
def add_evidence(
    dispute_id: str, body: EvidenceAdd, session: Session = Depends(get_session)
) -> Dispute:
    """Attach a new piece of evidence, then re-assess to see what it changes."""
    row = _load_dispute(session, dispute_id)
    bundle = row.evidence_items()
    bundle.append(
        EvidenceItem(type=body.type, content=body.content, source_ref=body.source_ref)
    )
    _bump_evidence(row, bundle)
    session.commit()
    logger.info("evidence added to %s (%d items, rev %d)", dispute_id, len(bundle), row.evidence_revision)
    return row.to_schema()


@router.delete(
    "/disputes/{dispute_id}/evidence/{index}",
    response_model=Dispute,
    tags=["disputes"],
)
def remove_evidence(
    dispute_id: str, index: int, session: Session = Depends(get_session)
) -> Dispute:
    """Remove a piece of evidence -- for the merchant who attached the wrong file."""
    row = _load_dispute(session, dispute_id)
    bundle = row.evidence_items()
    if not 0 <= index < len(bundle):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{dispute_id} has no evidence item at index {index}",
        )
    bundle.pop(index)
    _bump_evidence(row, bundle)
    session.commit()
    logger.info("evidence %d removed from %s (rev %d)", index, dispute_id, row.evidence_revision)
    return row.to_schema()


@router.get(
    "/disputes/{dispute_id}/urcs-forecast",
    response_model=URCSForecast,
    tags=["disputes"],
)
def urcs_forecast(dispute_id: str, session: Session = Depends(get_session)) -> URCSForecast:
    """What NPCI's URCS is expected to do with this chargeback, and why.

    A pure rules engine over counters -- no model, no LLM, no inference -- so this is
    cheap enough to call on every case-page load.
    """
    dispute = _load_dispute(session, dispute_id).to_schema()
    return forecast_urcs_disposition(dispute, _payer_history(session, dispute))


@router.get(
    "/disputes/{dispute_id}/evidence/{index}/document",
    response_model=EvidenceDocument,
    tags=["disputes"],
)
def evidence_document(
    dispute_id: str, index: int, session: Session = Depends(get_session)
) -> EvidenceDocument:
    """Open the record behind an evidence item's source_ref.

    The bundle's `source_ref` values used to be dangling strings. This resolves one to a
    document whose body is the evidence content verbatim -- see
    services/evidence_documents.py for why nothing may be added to it.
    """
    row = _load_dispute(session, dispute_id)
    items = row.evidence_items()
    if not 0 <= index < len(items):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{dispute_id} has no evidence item at index {index}",
        )
    return render_document(row.to_schema(), index, items[index])


@router.get("/disputes/{dispute_id}/evidence/{index}/download", tags=["disputes"])
def evidence_download(
    dispute_id: str, index: int, session: Session = Depends(get_session)
) -> PlainTextResponse:
    """The same record as a downloadable text file, for handing to an acquirer or auditor."""
    doc = evidence_document(dispute_id, index, session)
    lines = [doc.title, "=" * len(doc.title), ""]
    lines += [f"{f.label}: {f.value}" for f in doc.fields]
    lines += ["", doc.body, "", "--", doc.synthetic_notice]
    filename = f"{doc.source_ref or f'evidence_{index}'}.txt".replace("/", "_")
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    dispute = row.to_schema()
    history = _payer_history(session, dispute)

    engine = get_verification_engine()
    verdicts = engine.verify_bundle(row.claim_text, evidence, row.reason_code)
    result = aggregate(verdicts, evidence, dispute, history)

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
        dispute=dispute,
        dispute_history=history,
    )

    session.add(
        DecisionRow.from_schema(
            decision,
            rationale=result.rationale,
            urcs_forecast=result.urcs_forecast,
            evidence_revision=row.evidence_revision or 0,
        )
    )
    session.commit()

    logger.info(
        "decided %s -> %s (confidence %.3f)",
        dispute_id,
        decision.recommendation,
        decision.confidence,
    )
    return decision


@router.put(
    "/disputes/{dispute_id}/packet-draft",
    response_model=PacketDraft,
    tags=["disputes"],
)
def save_packet_draft(
    dispute_id: str, body: PacketDraft, session: Session = Depends(get_session)
) -> PacketDraft:
    """Save a merchant's in-progress edit of the representment.

    Before this, an edit lived only in React state: navigating away, or a reload, silently
    discarded however long they had spent rewriting the packet. The draft is saved against
    the decision it was written for, so re-assessing starts a clean draft rather than
    resurrecting text written against different verdicts.

    This is NOT approval, and it must not read as it. Nothing here touches
    approved_by_human or would_be_razorpay_payload -- only /approve does, and only when a
    human clicks it (Section 2.2).
    """
    row = _load_dispute(session, dispute_id)
    latest = row.latest_decision
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{dispute_id} has no decision yet; nothing to draft against.",
        )

    # An empty draft clears it, so "revert to the model's text" is expressible.
    latest.edited_packet = body.text or None
    session.commit()
    return PacketDraft(text=latest.edited_packet or "")


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


@router.post(
    "/disputes/{dispute_id}/withdraw",
    response_model=AuditLogEntry,
    tags=["disputes"],
)
def withdraw_approval(
    dispute_id: str, session: Session = Depends(get_session)
) -> AuditLogEntry:
    """Retract a standing approval and return the case to the queue.

    Approval was a one-way door: once a human clicked it the case read as approved forever,
    with no way to say "I was wrong" short of editing the database. For a system whose
    whole pitch is that a human stays in charge, the human being unable to change their
    mind is a strange gap.

    Recorded as a NEW audit entry rather than by editing or deleting the one it retracts.
    An audit trail that can be rewritten is not an audit trail, and the sequence
    approve -> withdraw -> approve is exactly the history a reviewer would want to see.
    """
    row = _load_dispute(session, dispute_id)
    if row.computed_status() not in {"approved", "submitted"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{dispute_id} has no standing approval to withdraw.",
        )

    latest = row.latest_decision
    entry = AuditLogRow(
        dispute_id=dispute_id,
        decision_id=latest.id,
        approved_by_human=False,
        submitted_to_razorpay=False,
        withdrawn=True,
        note=(
            "Human withdrew the earlier approval. The case returns to the queue. Nothing "
            "was transmitted at any point, so there is nothing to retract on Razorpay's "
            "side (CLAUDE.md Section 7)."
        ),
    )
    session.add(entry)
    session.commit()
    logger.info("approval WITHDRAWN for %s", dispute_id)
    return entry.to_schema()


# --- exports ---------------------------------------------------------------------------
# A packet a merchant cannot get out of the browser is a packet they cannot send to their
# acquirer, and the "would submit" payload is the artefact Section 7 exists to produce.


@router.get("/disputes/{dispute_id}/packet.txt", tags=["disputes"])
def export_packet(
    dispute_id: str, session: Session = Depends(get_session)
) -> PlainTextResponse:
    """The representment as a text file: the merchant's edit if there is one, else the draft."""
    row = _load_dispute(session, dispute_id)
    latest = row.latest_decision
    if latest is None or not (latest.edited_packet or latest.drafted_packet):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{dispute_id} has no drafted representment.",
        )

    text = latest.edited_packet or latest.drafted_packet or ""
    header = [
        f"Representment for {dispute_id}",
        f"Reason code: {row.reason_code}",
        f"Amount: INR {row.amount / 100:,.2f}",
        f"Recommendation: {latest.recommendation} ({latest.confidence:.0%} confidence)",
        f"Model: {latest.model_version}",
        "",
        "-" * 72,
        "",
    ]
    footer = [
        "",
        "-" * 72,
        "",
        "Drafted by Recourse. This dispute is synthetic and was never transmitted to "
        "Razorpay or any bank (CLAUDE.md Section 7). A human approved this text before "
        "export; the system never submits on its own.",
    ]
    return PlainTextResponse(
        NEWLINE.join(header + [text] + footer),
        headers={
            "Content-Disposition": f'attachment; filename="{dispute_id}_representment.txt"'
        },
    )


@router.get("/disputes/{dispute_id}/would-submit.json", tags=["disputes"])
def export_would_submit(
    dispute_id: str, session: Session = Depends(get_session)
) -> JSONResponse:
    """The exact payload that WOULD have gone to Razorpay, as a downloadable file.

    Section 7's honest artefact. Showing it on screen proves it exists; letting someone
    take it away is what makes it reviewable.
    """
    row = _load_dispute(session, dispute_id)
    entries = [e for e in row.audit_entries if e.would_be_razorpay_payload]
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{dispute_id} has no prepared submission payload.",
        )

    entry = sorted(entries, key=lambda e: e.id)[-1]
    return JSONResponse(
        content={
            "dispute_id": dispute_id,
            "prepared_at": entry.created_at.isoformat(),
            "transmitted": False,
            "why_not_transmitted": (
                "The dispute is synthetic and does not exist on Razorpay's side. The "
                "system never submits to a live dispute workflow (CLAUDE.md Sections 2 "
                "and 7)."
            ),
            "would_be_razorpay_payload": entry.would_be_razorpay_payload,
        },
        headers={
            "Content-Disposition": f'attachment; filename="{dispute_id}_would_submit.json"'
        },
    )


# --- backing a dispute with a real test-mode payment (Section 7) -----------------------
# Section 7 requires each dispute's payment_id to reference a REAL test-mode payment, and
# 181 of 182 seeded disputes still carry a pay_PENDING_ placeholder. The reason is not
# laziness: Razorpay exposes no endpoint that fabricates a payment. Orders are creatable
# over the API; payments only come into existence when someone completes a Checkout
# interaction, and this account has server-to-server payment creation disabled (both
# payment.createUpi and payment.createPaymentJson return 404), so there is no API-only
# route to a genuine pay_... id.
#
# These two endpoints implement the route that does exist, which is also the one a real
# merchant integration uses: create a real order, let Razorpay Checkout collect a test
# payment against it in the browser, then read the resulting payment id back off the order
# and promote it into the dispute. A human completes the payment. That is by design, not a
# gap -- and it is the same "a human acts, the system records" shape as /approve.


@router.post(
    "/disputes/{dispute_id}/backing-order",
    response_model=BackingOrder,
    tags=["disputes"],
)
def create_backing_order(
    dispute_id: str, session: Session = Depends(get_session)
) -> BackingOrder:
    """Create (or reuse) a real test-mode order to back this dispute."""
    row = _load_dispute(session, dispute_id)

    if not is_placeholder_payment_id(row.payment_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{dispute_id} is already backed by real payment {row.payment_id}.",
        )

    settings = get_settings()
    client = get_razorpay_client()

    # Reuse an order already created for this dispute rather than littering the account
    # with one per button press.
    if row.razorpay_order_id:
        try:
            order = client.fetch_order(row.razorpay_order_id)
            return BackingOrder(
                dispute_id=dispute_id,
                order_id=order["id"],
                amount=order["amount"],
                currency=order["currency"],
                key_id=settings.razorpay_key_id,
                description=f"Recourse backing for {dispute_id}",
                reused=True,
            )
        except RazorpayError:
            logger.warning(
                "stored order %s for %s no longer resolves; creating a new one",
                row.razorpay_order_id,
                dispute_id,
            )

    order = client.create_backing_order(row.amount, receipt=dispute_id[:40])
    row.razorpay_order_id = order["id"]
    session.commit()

    return BackingOrder(
        dispute_id=dispute_id,
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        key_id=settings.razorpay_key_id,
        description=f"Recourse backing for {dispute_id}",
        reused=False,
    )


@router.get(
    "/disputes/{dispute_id}/backing-status",
    response_model=BackingStatus,
    tags=["disputes"],
)
def backing_status(
    dispute_id: str, session: Session = Depends(get_session)
) -> BackingStatus:
    """Check the backing order for a completed payment, and promote it if there is one.

    Called after Checkout reports success, and safe to poll: promotion is idempotent
    because a dispute whose payment_id is already real short-circuits at the top.
    """
    row = _load_dispute(session, dispute_id)

    if not is_placeholder_payment_id(row.payment_id):
        return BackingStatus(
            dispute_id=dispute_id,
            payment_id=row.payment_id,
            payment_is_real=True,
            order_id=row.razorpay_order_id,
            message=f"Backed by real test-mode payment {row.payment_id}.",
        )

    if not row.razorpay_order_id:
        return BackingStatus(
            dispute_id=dispute_id,
            payment_id=row.payment_id,
            payment_is_real=False,
            message="No backing order yet. Start one to attach a real test payment.",
        )

    client = get_razorpay_client()
    try:
        order = client.fetch_order(row.razorpay_order_id)
        payments = client.fetch_order_payments(row.razorpay_order_id)
    except RazorpayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    # Only a payment Razorpay actually holds money against counts. An attempt that failed
    # or was abandoned must not be promoted -- that would put a dead id on the dispute and
    # make the "real payment" claim false, which is the one thing this flow exists to make
    # true.
    usable = [p for p in payments if p.get("status") in {"captured", "authorized"}]

    if not usable:
        return BackingStatus(
            dispute_id=dispute_id,
            payment_id=row.payment_id,
            payment_is_real=False,
            order_id=row.razorpay_order_id,
            order_status=order.get("status"),
            payments_seen=len(payments),
            message=(
                "Order is live but no completed payment yet. "
                "Finish the test checkout to attach one."
            ),
        )

    promoted = usable[0]["id"]
    previous = row.payment_id
    row.payment_id = promoted
    session.commit()
    logger.info("promoted %s: %s -> real payment %s", dispute_id, previous, promoted)

    return BackingStatus(
        dispute_id=dispute_id,
        payment_id=promoted,
        payment_is_real=True,
        order_id=row.razorpay_order_id,
        order_status=order.get("status"),
        payments_seen=len(payments),
        message=f"Attached real test-mode payment {promoted}.",
    )


# --- conformal risk control (Addendum 3) ----------------------------------------------


def _calibration_pairs(cache: dict) -> list[tuple[float, str]]:
    return [
        (r["score"], r["label"]) for r in cache["calibration"] if r["score"] is not None
    ]


@router.post("/calibrate", response_model=CalibrationResult, tags=["calibration"])
def calibrate(
    body: CalibrateRequest, session: Session = Depends(get_session)
) -> CalibrationResult:
    """Calibrate the decision threshold to a stated maximum false-positive rate.

    Replays the threshold search over cached scores, so this is instant regardless of how
    many times the slider moves.
    """
    cache = load_scores()
    if not cache:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No calibration scores available. Build them with "
                "`python eval/build_conformal_cache.py`."
            ),
        )

    pairs = _calibration_pairs(cache)
    lam = calibrate_threshold(pairs, body.alpha, body.delta)
    set_active_threshold(lam, body.alpha, body.delta)

    # Persisted so a restart does not silently revert the operator's budget to a built-in
    # default. The threshold decides every recommendation, so losing it changes what the
    # product does with nothing in the record to explain why.
    session.add(
        CalibrationRow(
            alpha=body.alpha,
            delta=body.delta,
            threshold=lam,
            calibration_set_size=len(pairs),
        )
    )
    session.commit()

    r_hat, n_lam = (None, 0) if lam is None else empirical_fp_rate(pairs, lam)
    floor = smallest_achievable_alpha(pairs, body.delta)

    statement = (
        guarantee_statement(body.alpha, body.delta)
        if lam is not None
        else (
            f"A {body.alpha:.0%} false-positive budget is not achievable on this "
            f"calibration set"
            + (f"; the tightest it can support is {floor:.0%}." if floor else ".")
            + " The system will defer every case rather than promise something the data "
            "does not support."
        )
    )

    return CalibrationResult(
        alpha=body.alpha,
        delta=body.delta,
        calibrated_threshold=lam,
        achievable=lam is not None,
        calibration_set_size=len(pairs),
        n_above_threshold=n_lam,
        empirical_fp_rate_on_calibration=r_hat,
        hoeffding_slack=hoeffding_slack(n_lam, body.delta) if n_lam else None,
        guarantee_statement=statement,
        smallest_achievable_alpha=floor,
    )


@router.get("/verify-guarantee", response_model=GuaranteeVerification, tags=["calibration"])
def verify_guarantee() -> GuaranteeVerification:
    """Check whether the active threshold's guarantee actually held on the TEST split.

    This endpoint exists so the system can prove itself wrong. It reads only the test
    split, which shares no dispute ids with the calibration data.
    """
    cache = load_scores()
    if not cache:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No calibration scores available.",
        )

    state = active_state()
    lam, alpha = state["threshold"], state["alpha"]
    test = cache["test"]

    if lam is None or alpha is None:
        # Nothing is auto-contested, so the false-positive rate is vacuously zero and
        # coverage is zero. Reporting that plainly beats refusing to answer.
        return GuaranteeVerification(
            alpha=alpha if alpha is not None else 0.0,
            observed_fp_rate_on_test=0.0,
            guarantee_held=True,
            coverage=0.0,
            n_test=len(test),
        )

    contested = [r for r in test if r["score"] is not None and r["score"] >= lam]
    fps = sum(1 for r in contested if r["label"] != "contest_win")
    observed = fps / len(contested) if contested else 0.0

    # Coverage counts every case the system settles without a human: contests, accepts,
    # and the URCS auto-rejects that never needed a decision at all.
    decided = sum(
        1
        for r in test
        if r["urcs_auto_reject"]
        or (r["max_contradict"] is not None and r["max_contradict"] >= lam)
        or (r["score"] is not None and r["score"] >= lam)
    )

    return GuaranteeVerification(
        alpha=alpha,
        observed_fp_rate_on_test=round(observed, 4),
        guarantee_held=observed <= alpha,
        coverage=round(decided / len(test), 4) if test else 0.0,
        n_test=len(test),
    )


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
