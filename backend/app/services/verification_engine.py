"""NLI verification engine: checks each evidence item against the bank's claim.

The model is the pretrained cross-encoder `cross-encoder/nli-deberta-v3-base` (CLAUDE.md
Section 3), run locally. No LLM API is involved in this decision: it must be deterministic,
free to run thousands of times during evaluation, and reproducible by anyone.

THE LABEL INVERSION -- the single most important detail in this file
--------------------------------------------------------------------
The model scores an ordered pair (premise, hypothesis). We pass:

    premise    = the merchant's evidence
    hypothesis = claim_text, which is the BANK'S ACCUSATION against the merchant

So the NLI label is a statement about the bank's claim, not the merchant's position, and
the mapping into ClaimVerdict inverts:

    NLI contradiction  evidence refutes the bank's claim   -> verdict "support"
                                                              (supports CONTESTing)
    NLI entailment     evidence confirms the bank's claim  -> verdict "contradict"
                                                              (contradicts the merchant)
    NLI neutral        evidence does not resolve it        -> verdict "neutral"

Getting this backwards would invert every recommendation while still producing
plausible-looking confidence scores, so it is pinned by tests in
tests/test_verification_engine.py.

Verified against the installed model at build time:
    model.config.id2label == {0: 'contradiction', 1: 'entailment', 2: 'neutral'}
which matches the order SBERT documents. _assert_label_order() re-checks this at load
time rather than trusting it, because a silent reordering in a future model revision would
corrupt every verdict.

WHY THERE ARE TWO SIGNALS AND NOT ONE
--------------------------------------
Scoring evidence against the bank's claim alone does not work. Measured on the working set
(182 records, held-out untouched), that naive formulation under Section 10's rule gave:

    precision 0.481   recall 0.765   coverage 0.423   false-positive cost Rs 42,000

Precision below 0.5 means it recommended CONTEST on losing cases MORE often than winning
ones (contest_loss 40% vs contest_win 35%) -- worse than a coin flip, and it would cost a
merchant money. The cause is representational, not a tuning problem: a strong delivery
proof and a weak one BOTH textually contradict "never delivered", so entailment alone
cannot perceive evidentiary strength, which is the actual discriminator. Confidence was
also useless -- 82% of verdicts sat at ~1.00, so Section 10's 0.7 / 0.65 gates never bound.

So each evidence item is scored on two axes:

  ENGAGEMENT    NLI(evidence, bank's claim) -> contradiction probability.
                "Does this evidence even address the accusation?"
                Saturated and easy: nearly anything on-topic scores high.

  SUBSTANTIATION NLI(each sentence, a short reason-code-specific probe) -> max entailment.
                "Is this evidence SPECIFIC enough to prove the merchant's position?"
                Genuinely discriminative. A bare 'delivered' scan engages the claim but
                does not entail "The customer received the goods"; a signature plus OTP
                plus a matching name does.

confidence for a supporting verdict is an equal-weight blend of the two. That matters
beyond scoring: Section 10 gates CONTEST on avg(confidence) > 0.65 and reports overall
confidence as the min across verdicts. Because confidence now carries evidentiary
strength, those gates do real work and Section 10's "a chain of evidence is only as strong
as its weakest link" rationale becomes literally true rather than decorative.

Measured on the working set, the blend moved precision 0.481 -> 0.625 and false-positive
cost Rs 42,000 -> Rs 9,000, at the cost of coverage 0.423 -> 0.214. That is the right
trade for this product: fewer, better auto-decisions, with the remainder routed to a human
rather than guessed at (CLAUDE.md Section 1).

All thresholds here were chosen on the WORKING set only. eval/held_out_set.json was not
inspected (Section 9). The model is zero-shot, not fine-tuned; fine-tuning is the obvious
route to better numbers and is explicitly a stretch goal (Section 16).
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np

from app.models.schemas import ClaimVerdict, EvidenceItem, VerdictLabel

logger = logging.getLogger("recourse.verification")

MODEL_NAME = "cross-encoder/nli-deberta-v3-base"
# Pin the exact weights used for the recorded evaluation. A model repository name alone
# is not reproducible: its default branch can move while old decisions continue to report
# the same apparent version. This is the commit already present in the local HF cache.
MODEL_REVISION = "6c749ce3425cd33b46d187e45b92bbf96ee12ec7"
MODEL_VERSION = f"{MODEL_NAME}@{MODEL_REVISION}"

# Index order of the model's output logits.
NLI_LABELS = ("contradiction", "entailment", "neutral")
IDX_CONTRADICTION, IDX_ENTAILMENT, IDX_NEUTRAL = 0, 1, 2

# NLI label -> ClaimVerdict label. See the module docstring: this inverts on purpose.
NLI_TO_VERDICT: dict[str, VerdictLabel] = {
    "contradiction": "support",
    "entailment": "contradict",
    "neutral": "neutral",
}

# A sentence must have at least this many characters to be considered as a highlight span;
# below this it is usually a fragment like "IST." and makes a poor explanation.
MIN_SPAN_CHARS = 25

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

# --- two-signal tuning constants (chosen on the WORKING set; see module docstring) ---

# Equal weight to engagement and substantiation. Deliberately 0.50 rather than a
# grid-searched decimal: it is defensible as a stated design choice, and the sweep showed
# neighbouring values (0.55, 0.60) are strictly worse on precision anyway.
ENGAGEMENT_WEIGHT = 0.50

# Above this entailment of the bank's claim, the evidence actively damns the merchant.
DAMNING_THRESHOLD = 0.50

# Below this contradiction of the bank's claim, the evidence does not engage it at all.
ENGAGEMENT_THRESHOLD = 0.50

# A "support" verdict must clear this, otherwise the label is downgraded to neutral.
#
# Set at 0.45 deliberately, and NOT higher. A "support" verdict here means "this item does
# not undermine the merchant", not "this item single-handedly proves the case" -- real
# bundles pair one decisive item with contextual ones ("nine prior orders, none disputed")
# that legitimately substantiate close to zero. Evidentiary strength lives in `confidence`,
# and Section 10 gates the BUNDLE on avg(confidence) > 0.65, which is the right level for
# that judgement.
#
# Measured on the working set: raising this to 0.50 downgrades one contextual item in six
# otherwise-winning bundles, and because Section 10 requires ALL verdicts to be "support",
# each downgrade kills the whole bundle -- recall 0.556 -> 0.333 and precision 0.625 ->
# 0.571. Values of 0.00, 0.40 and 0.45 all score identically, so 0.45 is chosen as the
# loosest value that still keeps the label semantically honest.
SUPPORT_FLOOR = 0.45

# Short, MNLI-style probes: what the merchant must actually have proved, per reason code.
# Deliberately short declaratives -- an earlier round used long specification-style
# hypotheses and scored near zero everywhere, because SNLI/MNLI hypotheses are short.
SUBSTANTIATION_PROBES: dict[str, str] = {
    "goods_not_received": "The customer received the goods.",
    "goods_not_as_described": "The item matched its description.",
    "duplicate_charge": "The two charges were for different purchases.",
    "unrecognized_transaction": "The cardholder authorised this purchase.",
    "subscription_cancelled": "The charge was made before the cancellation.",
    "credit_not_processed": "The refund was paid to the customer.",
}

GENERIC_PROBE = "The merchant's account of what happened is correct."


def probe_for(reason_code: str) -> str:
    """Return the substantiation probe for a reason code, falling back to a generic one.

    Unknown reason codes degrade to the generic probe rather than raising: real acquirers
    emit codes outside any fixed list.
    """
    return SUBSTANTIATION_PROBES.get(reason_code, GENERIC_PROBE)


def split_sentences(text: str) -> list[str]:
    """Split evidence into sentences for span attribution.

    Deliberately a simple regex rather than an NLP sentence tokeniser: it adds no
    dependency, is fully deterministic, and Section 3 asks for a clear explainable
    heuristic over a clever opaque one.
    """
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text.strip()) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def softmax(logits: np.ndarray) -> np.ndarray:
    """Row-wise softmax. The model emits raw logits; ClaimVerdict.confidence needs 0-1."""
    logits = np.asarray(logits, dtype=np.float64)
    if logits.ndim == 1:
        logits = logits.reshape(1, -1)
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


@dataclass
class EvidenceAssessment:
    """Full per-evidence detail. ClaimVerdict is the trimmed public view of this.

    The extra fields exist so the audit trail can show *why* a verdict landed where it
    did -- an engagement of 0.99 with a substantiation of 0.02 is the signature of
    evidence that talks about the right subject while proving nothing.
    """

    evidence_index: int
    verdict: VerdictLabel
    confidence: float
    engagement: float  # contradiction of the bank's claim
    substantiation: float  # entailment of the reason-code probe
    damning: float  # entailment of the bank's claim
    highlighted_span: Optional[str]

    def to_claim_verdict(self) -> ClaimVerdict:
        return ClaimVerdict(
            evidence_index=self.evidence_index,
            label=self.verdict,
            confidence=round(self.confidence, 4),
            highlighted_span=self.highlighted_span,
        )


class VerificationEngine:
    """Wraps the cross-encoder. Model load is lazy and thread-safe."""

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        model_revision: str = MODEL_REVISION,
    ) -> None:
        self.model_name = model_name
        self.model_revision = model_revision
        self._model = None
        self._lock = threading.Lock()
        # A separate lock for inference. HuggingFace's fast tokenizer is a Rust object
        # that panics with "RuntimeError: Already borrowed" if two threads call into it
        # at once, and FastAPI runs sync endpoints in a threadpool -- so two concurrent
        # /decide requests (two browser tabs, or a batch assessment) would 500 without
        # this. Must not be self._lock: the model property holds that during load and
        # threading.Lock is not reentrant.
        self._predict_lock = threading.Lock()

    # -- model lifecycle ----------------------------------------------------

    @property
    def model(self):
        """Load on first use so importing this module never triggers a download."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder

                    logger.info(
                        "loading NLI cross-encoder %s@%s",
                        self.model_name,
                        self.model_revision,
                    )
                    model = CrossEncoder(self.model_name, revision=self.model_revision)
                    _assert_label_order(model)
                    self._model = model
                    logger.info("NLI cross-encoder ready")
        return self._model

    def warmup(self) -> None:
        """Force the model to load now (used at API startup to avoid a slow first request)."""
        self.predict_proba([("warmup premise text.", "warmup hypothesis text.")])

    # -- scoring ------------------------------------------------------------

    def predict_proba(self, pairs: Sequence[tuple[str, str]]) -> np.ndarray:
        """Return an (n, 3) probability matrix over (contradiction, entailment, neutral)."""
        if not pairs:
            return np.empty((0, 3), dtype=np.float64)
        model = self.model  # may block on first load; do it outside the inference lock
        with self._predict_lock:
            logits = model.predict(list(pairs))
        return softmax(np.asarray(logits))

    def verify_bundle(
        self,
        claim_text: str,
        evidence_bundle: Iterable[EvidenceItem],
        reason_code: str = "",
    ) -> list[ClaimVerdict]:
        """Score every evidence item against the claim and return one verdict each."""
        return [
            a.to_claim_verdict()
            for a in self.assess_bundle(claim_text, evidence_bundle, reason_code)
        ]

    def assess_bundle(
        self,
        claim_text: str,
        evidence_bundle: Iterable[EvidenceItem],
        reason_code: str = "",
    ) -> list[EvidenceAssessment]:
        """Full two-signal assessment. See the module docstring for why there are two."""
        items = list(evidence_bundle)
        if not items:
            return []

        probe = probe_for(reason_code)

        # Signal 1, batched: does each evidence item engage/affirm the bank's claim?
        claim_probs = self.predict_proba([(item.content, claim_text) for item in items])

        assessments: list[EvidenceAssessment] = []
        for index, (item, probs) in enumerate(zip(items, claim_probs)):
            engagement = float(probs[IDX_CONTRADICTION])
            damning = float(probs[IDX_ENTAILMENT])

            # Signal 2: does any single sentence substantiate the merchant's position?
            # Sentence-level because the decisive fact is usually one clause inside a
            # paragraph of boilerplate.
            sentences = split_sentences(item.content) or [item.content]
            probe_probs = self.predict_proba([(s, probe) for s in sentences])
            substantiation_per_sentence = probe_probs[:, IDX_ENTAILMENT]
            best_sentence_idx = int(np.argmax(substantiation_per_sentence))
            substantiation = float(substantiation_per_sentence[best_sentence_idx])

            verdict, confidence, span = self._decide(
                engagement=engagement,
                damning=damning,
                substantiation=substantiation,
                sentences=sentences,
                best_substantiating_idx=best_sentence_idx,
                claim_text=claim_text,
            )

            assessments.append(
                EvidenceAssessment(
                    evidence_index=index,
                    verdict=verdict,
                    confidence=confidence,
                    engagement=engagement,
                    substantiation=substantiation,
                    damning=damning,
                    highlighted_span=span,
                )
            )
        return assessments

    def _decide(
        self,
        *,
        engagement: float,
        damning: float,
        substantiation: float,
        sentences: list[str],
        best_substantiating_idx: int,
        claim_text: str,
    ) -> tuple[VerdictLabel, float, Optional[str]]:
        """Turn the two signals into a verdict, a confidence and an explanatory span."""
        # 1. Evidence that affirms the bank's claim condemns the merchant outright.
        if damning > DAMNING_THRESHOLD:
            span = self._span_by_claim_label(sentences, claim_text, IDX_ENTAILMENT)
            return "contradict", damning, span

        # 2. Evidence that engages the claim: strength decides how much it is worth.
        if engagement > ENGAGEMENT_THRESHOLD:
            blended = ENGAGEMENT_WEIGHT * engagement + (1 - ENGAGEMENT_WEIGHT) * substantiation
            if blended >= SUPPORT_FLOOR:
                # The substantiating sentence is the honest explanation of a support
                # verdict: it is the line that actually proves something.
                return "support", blended, self._pick(sentences, best_substantiating_idx)
            # On-topic but proves nothing. Badging this green would mislead the reviewer.
            return "neutral", 1.0 - blended, self._pick(sentences, best_substantiating_idx)

        # 3. Evidence that does not engage the claim at all.
        neutrality = 1.0 - max(engagement, damning)
        return "neutral", neutrality, self._span_by_claim_label(
            sentences, claim_text, IDX_NEUTRAL
        )

    # -- explainability -----------------------------------------------------

    @staticmethod
    def _pick(sentences: list[str], index: int) -> Optional[str]:
        if not sentences:
            return None
        chosen = sentences[min(index, len(sentences) - 1)]
        # Prefer a substantive sentence when the winner is a short fragment.
        if len(chosen) < MIN_SPAN_CHARS:
            longer = [s for s in sentences if len(s) >= MIN_SPAN_CHARS]
            if longer:
                return longer[0]
        return chosen

    def _span_by_claim_label(
        self, sentences: list[str], claim_text: str, label_idx: int
    ) -> Optional[str]:
        """Surface the sentence scoring highest for a given label against the claim.

        Section 3's prescribed approach: split the evidence into sentences, score each
        independently with the same cross-encoder, and surface the top one.
        """
        if not sentences:
            return None
        if len(sentences) == 1:
            return sentences[0]
        candidates = [s for s in sentences if len(s) >= MIN_SPAN_CHARS] or sentences
        probs = self.predict_proba([(s, claim_text) for s in candidates])
        return candidates[int(np.argmax(probs[:, label_idx]))]


def _assert_label_order(model) -> None:
    """Fail loudly if the model's label order is not the one this module assumes."""
    id2label = getattr(getattr(model, "model", None), "config", None)
    id2label = getattr(id2label, "id2label", None)
    if not id2label:
        logger.warning("model exposes no id2label; assuming %s", NLI_LABELS)
        return
    actual = tuple(str(id2label[i]).lower() for i in sorted(id2label))
    if actual != NLI_LABELS:
        raise RuntimeError(
            f"NLI label order changed: expected {NLI_LABELS}, model reports {actual}. "
            "Every verdict in this system depends on this order; refusing to continue."
        )


# Process-wide singleton: the model is ~750MB and must not be loaded per request.
_engine: Optional[VerificationEngine] = None
_engine_lock = threading.Lock()


def get_verification_engine() -> VerificationEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = VerificationEngine()
    return _engine


def model_is_loaded() -> bool:
    """Whether the cross-encoder is in memory and ready to score."""
    return _engine is not None and _engine._model is not None


def warm_up() -> None:
    """Load the model and run one throwaway prediction.

    The first /decide used to pay the whole ~15s load, which the UI had to apologise for
    mid-interaction. Called on a background thread at startup so the process serves
    immediately and the cost lands before anyone clicks rather than during their click.

    Failure here is not fatal: a warm-up that cannot reach the model hub must leave the app
    running, so the first real request retries the load and surfaces the error there.
    """
    try:
        engine = get_verification_engine()
        engine.model.predict([("warm up", "warm up")])
        logger.info("NLI cross-encoder warmed up")
    except Exception as exc:  # noqa: BLE001 -- warm-up must never stop the app booting
        logger.warning("model warm-up failed (%s); it will load on first use", exc)


__all__ = [
    "DAMNING_THRESHOLD",
    "ENGAGEMENT_THRESHOLD",
    "ENGAGEMENT_WEIGHT",
    "GENERIC_PROBE",
    "IDX_CONTRADICTION",
    "IDX_ENTAILMENT",
    "IDX_NEUTRAL",
    "MODEL_NAME",
    "MODEL_REVISION",
    "MODEL_VERSION",
    "model_is_loaded",
    "warm_up",
    "NLI_LABELS",
    "NLI_TO_VERDICT",
    "SUBSTANTIATION_PROBES",
    "SUPPORT_FLOOR",
    "EvidenceAssessment",
    "VerificationEngine",
    "get_verification_engine",
    "probe_for",
    "split_sentences",
    "softmax",
]
