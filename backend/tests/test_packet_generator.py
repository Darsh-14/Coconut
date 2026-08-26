"""Packet drafting tests (CLAUDE.md Section 13, phase 6).

The load-bearing property is that drafting is NEVER allowed to lose a decision. The
decision is made by the NLI engine before this module runs; an LLM outage, a bad key, a
rate limit or a malformed response must all degrade to the deterministic template rather
than propagate. Several tests inject each of those failures deliberately.

No network access and no API key required: the LLM path is stubbed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.models.schemas import ClaimVerdict, Dispute, EvidenceItem
from app.services import packet_generator
from app.services.packet_generator import build_template_packet, generate_packet


def make_dispute() -> Dispute:
    raised = datetime.now(timezone.utc) - timedelta(days=2)
    return Dispute(
        dispute_id="disp_synthetic_0500",
        payment_id="pay_TUSjwsBKtOQpWj",
        phase="chargeback",
        reason_code="goods_not_received",
        claim_text="Cardholder asserts the merchandise was never delivered.",
        amount=249900,
        raised_at=raised,
        respond_by=raised + timedelta(days=21),
        evidence_bundle=[
            EvidenceItem(
                type="delivery_proof",
                content=(
                    "The recipient signed for the parcel on 14 July 2026. The delivery OTP "
                    "was entered from the registered mobile."
                ),
                source_ref="pod_500",
            ),
            EvidenceItem(
                type="communication_log",
                content="The customer replied 'received, thanks' on 14 July 2026.",
                source_ref="sms_500",
            ),
        ],
        ground_truth_label="contest_win",
    )


SUPPORTING = [
    ClaimVerdict(
        evidence_index=0,
        label="support",
        confidence=0.91,
        highlighted_span="The recipient signed for the parcel on 14 July 2026.",
    ),
    ClaimVerdict(evidence_index=1, label="support", confidence=0.74),
]


# -- template path ---------------------------------------------------------------------


def test_template_cites_the_specific_evidence():
    packet = build_template_packet(make_dispute(), SUPPORTING)
    assert "pod_500" in packet
    assert "sms_500" in packet
    assert "signed for the parcel" in packet


def test_template_quotes_the_highlighted_span():
    """The engine identified the decisive sentence; the packet must actually use it."""
    packet = build_template_packet(make_dispute(), SUPPORTING)
    assert "Most material:" in packet
    assert "The recipient signed for the parcel on 14 July 2026." in packet


def test_template_reports_the_weakest_link_not_the_average():
    """Section 10's min() rationale has to survive into the customer-facing document."""
    packet = build_template_packet(make_dispute(), SUPPORTING)
    assert "74%" in packet, "should report the weakest supporting verdict (0.74)"
    assert "weakest link" in packet


def test_template_states_it_was_not_submitted():
    packet = build_template_packet(make_dispute(), SUPPORTING)
    assert "Not submitted" in packet


def test_template_formats_rupees():
    assert "Rs 2,499.00" in build_template_packet(make_dispute(), SUPPORTING)


def test_template_omits_non_supporting_evidence():
    verdicts = [
        ClaimVerdict(evidence_index=0, label="support", confidence=0.9),
        ClaimVerdict(evidence_index=1, label="neutral", confidence=0.5),
    ]
    packet = build_template_packet(make_dispute(), verdicts)
    assert "pod_500" in packet
    assert "sms_500" not in packet, "neutral evidence must not be cited as support"


def test_no_packet_without_supporting_evidence():
    verdicts = [ClaimVerdict(evidence_index=0, label="contradict", confidence=0.9)]
    assert generate_packet(make_dispute(), verdicts) is None


def test_out_of_range_index_is_skipped_not_fatal():
    verdicts = [ClaimVerdict(evidence_index=99, label="support", confidence=0.9)]
    packet = generate_packet(make_dispute(), verdicts, prefer_llm=False)
    assert packet is not None  # degrades rather than raising


# -- failure recovery: drafting must never lose a decision -----------------------------


@pytest.mark.uses_llm
@pytest.mark.parametrize(
    "boom",
    [
        RuntimeError("provider exploded"),
        TimeoutError("rate limited"),
        ValueError("malformed response"),
    ],
)
def test_llm_failure_falls_back_to_template(monkeypatch, boom):
    def explode(*_args, **_kwargs):
        raise boom

    monkeypatch.setattr("app.services.packet_llm.draft_with_llm", explode)
    packet = generate_packet(make_dispute(), SUPPORTING, prefer_llm=True)
    assert packet is not None
    assert "REPRESENTMENT" in packet, "must be the template"
    assert "pod_500" in packet


@pytest.mark.uses_llm
def test_llm_returning_none_falls_back_to_template(monkeypatch):
    monkeypatch.setattr("app.services.packet_llm.draft_with_llm", lambda *a, **k: None)
    packet = generate_packet(make_dispute(), SUPPORTING, prefer_llm=True)
    assert "REPRESENTMENT" in packet


@pytest.mark.uses_llm
def test_llm_output_is_used_when_it_succeeds(monkeypatch):
    monkeypatch.setattr(
        "app.services.packet_llm.draft_with_llm",
        lambda *a, **k: "Polished letter citing pod_500 and sms_500.",
    )
    packet = generate_packet(make_dispute(), SUPPORTING, prefer_llm=True)
    assert packet == "Polished letter citing pod_500 and sms_500."


@pytest.mark.uses_llm
def test_prefer_llm_false_skips_the_provider_entirely(monkeypatch):
    def explode(*_a, **_k):
        raise AssertionError("provider must not be called when prefer_llm=False")

    monkeypatch.setattr("app.services.packet_llm.draft_with_llm", explode)
    assert "REPRESENTMENT" in generate_packet(make_dispute(), SUPPORTING, prefer_llm=False)


# -- provider resolution ---------------------------------------------------------------


def _settings(monkeypatch, **env) -> Settings:
    base = {
        "RAZORPAY_KEY_ID": "rzp_test_abc",
        "RAZORPAY_KEY_SECRET": "s",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "LLM_PROVIDER": "auto",
    }
    base.update(env)
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    return Settings(load_env_file=False)


def test_auto_prefers_gemini_when_both_keys_present(monkeypatch):
    s = _settings(monkeypatch, GEMINI_API_KEY="g", ANTHROPIC_API_KEY="a")
    assert s.resolve_llm_provider() == "gemini"


def test_auto_falls_back_to_anthropic(monkeypatch):
    s = _settings(monkeypatch, ANTHROPIC_API_KEY="a")
    assert s.resolve_llm_provider() == "anthropic"


def test_auto_resolves_to_none_without_any_key(monkeypatch):
    assert _settings(monkeypatch).resolve_llm_provider() == "none"


def test_forcing_a_provider_without_its_key_resolves_to_none(monkeypatch):
    """Forcing gemini with no Gemini key must template, not silently use Anthropic."""
    s = _settings(monkeypatch, LLM_PROVIDER="gemini", ANTHROPIC_API_KEY="a")
    assert s.resolve_llm_provider() == "none"


def test_provider_none_is_respected_even_with_keys(monkeypatch):
    s = _settings(monkeypatch, LLM_PROVIDER="none", GEMINI_API_KEY="g")
    assert s.resolve_llm_provider() == "none"


def test_google_api_key_is_accepted_as_an_alias(monkeypatch):
    s = _settings(monkeypatch, GOOGLE_API_KEY="g")
    assert s.gemini_configured is True


def test_invalid_provider_is_rejected_at_startup(monkeypatch):
    from app.config import ConfigError

    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        _settings(monkeypatch, LLM_PROVIDER="openai")


def test_draft_with_llm_returns_none_when_provider_is_none(monkeypatch):
    from app.services import packet_llm

    _settings(monkeypatch, LLM_PROVIDER="none")
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(load_env_file=False))
    monkeypatch.setattr(packet_llm, "get_settings", lambda: Settings(load_env_file=False))
    assert packet_llm.draft_with_llm(make_dispute(), SUPPORTING, "template") is None


# -- grounding guard -------------------------------------------------------------------


@pytest.mark.uses_llm
def test_llm_draft_dropping_all_source_refs_is_rejected(monkeypatch):
    """Fluent prose that cites nothing is worse than the template. Reject it."""
    from app.services import packet_llm

    monkeypatch.setattr(packet_llm, "get_settings", lambda: _FakeSettings("gemini"))
    monkeypatch.setattr(packet_llm, "_draft_with_gemini", lambda _p: "Nice prose, no references.")
    assert packet_llm.draft_with_llm(make_dispute(), SUPPORTING, "template") is None


@pytest.mark.uses_llm
def test_llm_draft_keeping_a_source_ref_is_accepted(monkeypatch):
    from app.services import packet_llm

    monkeypatch.setattr(packet_llm, "get_settings", lambda: _FakeSettings("gemini"))
    monkeypatch.setattr(
        packet_llm, "_draft_with_gemini", lambda _p: "Prose citing pod_500 properly."
    )
    result = packet_llm.draft_with_llm(make_dispute(), SUPPORTING, "template")
    assert result == "Prose citing pod_500 properly."


class _FakeSettings:
    def __init__(self, provider: str):
        self._provider = provider
        self.gemini_api_key = "x"
        self.gemini_model = ""
        self.anthropic_api_key = ""
        self.anthropic_model = "claude-sonnet-5"

    def resolve_llm_provider(self) -> str:
        return self._provider
