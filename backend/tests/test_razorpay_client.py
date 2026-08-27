"""Guards for the real-vs-synthetic boundary (CLAUDE.md Sections 2, 3 and 7).

The property under test: a synthetic dispute id must never produce a network call, in any
code path, for any action. These tests install a sentinel in place of the SDK client that
raises if it is touched, so a regression fails loudly rather than quietly calling Razorpay.

No credentials are required to run these.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.razorpay_client import (
    PENDING_PAYMENT_PREFIX,
    SYNTHETIC_DISPUTE_PREFIX,
    RazorpayClient,
    build_contest_payload,
    is_placeholder_payment_id,
    is_synthetic_dispute_id,
    may_reach_razorpay,
)


class ExplodingSDK:
    """Stands in for razorpay.Client. Any attribute access is a test failure."""

    def __getattr__(self, name):
        raise AssertionError(f"network call attempted: razorpay.Client.{name}")


class RecordingDispute:
    """Records dispute calls instead of sending them, for the non-synthetic path."""

    def __init__(self):
        self.calls = []

    def _record(self, action):
        def _call(dispute_id, data=None):
            self.calls.append((action, dispute_id, data))
            return {"id": dispute_id, "status": f"{action}ed"}

        return _call

    def __getattr__(self, name):
        if name in {"fetch", "accept", "contest"}:
            return self._record(name)
        raise AttributeError(name)


class RecordingSDK:
    def __init__(self):
        self.dispute = RecordingDispute()


@pytest.fixture
def settings(monkeypatch) -> Settings:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ASSUMED_REPRESENTMENT_COST_INR", "1500")
    return Settings(load_env_file=False)


@pytest.fixture
def client(settings) -> RazorpayClient:
    c = RazorpayClient(settings=settings)
    c._client = ExplodingSDK()
    return c


# -- id classification ---------------------------------------------------------------


def test_synthetic_ids_are_recognised():
    assert is_synthetic_dispute_id(f"{SYNTHETIC_DISPUTE_PREFIX}0001")
    assert not is_synthetic_dispute_id("disp_NkQ8vRt2mWxYz1")


def test_placeholder_payment_ids_are_recognised():
    assert is_placeholder_payment_id(f"{PENDING_PAYMENT_PREFIX}0001")
    assert not is_placeholder_payment_id("pay_NkQ8vRt2mWxYz1")


# -- the core safety property --------------------------------------------------------


@pytest.mark.parametrize("action", ["fetch", "accept", "contest"])
def test_synthetic_dispute_never_calls_the_network(client, action):
    """ExplodingSDK raises on any attribute access, so reaching the SDK fails the test."""
    dispute_id = f"{SYNTHETIC_DISPUTE_PREFIX}0042"
    if action == "contest":
        result = client.contest_dispute(dispute_id, {"summary": "drafted text"})
    elif action == "accept":
        result = client.accept_dispute(dispute_id)
    else:
        result = client.fetch_dispute(dispute_id)

    assert result.submitted is False
    assert result.response is None
    assert result.dispute_id == dispute_id
    assert "synthetic" in result.reason.lower()


def test_synthetic_contest_records_the_payload_it_would_have_sent(client):
    dispute_id = f"{SYNTHETIC_DISPUTE_PREFIX}0007"
    body = {"amount": 249900, "summary": "Delivery confirmed by OTP and signature."}
    result = client.contest_dispute(dispute_id, body)

    payload = result.would_be_payload
    assert payload["method"] == "PATCH"
    assert payload["path"] == f"/v1/disputes/{dispute_id}/contest"
    assert payload["body"] == body


def test_synthetic_accept_uses_post_and_the_accept_path(client):
    dispute_id = f"{SYNTHETIC_DISPUTE_PREFIX}0008"
    payload = client.accept_dispute(dispute_id).would_be_payload
    assert payload["method"] == "POST"
    assert payload["path"] == f"/v1/disputes/{dispute_id}/accept"


def test_placeholder_payment_fetch_returns_none_without_calling(client):
    assert client.fetch_payment(f"{PENDING_PAYMENT_PREFIX}0001") is None


# -- the guard fails closed ----------------------------------------------------------
# It used to test "is this id synthetic?" and send anything else. That is an allowlist
# written inside out: any id the system had not anticipated -- a manually filed dispute, a
# typo, a prefix added later -- would have been treated as a genuine Razorpay dispute and
# transmitted, against Section 2.2. These pin the inverted rule.


def test_an_unrecognised_dispute_id_is_not_sent(settings):
    """The case that used to send. A real-looking id is still not a real dispute here."""
    client = RazorpayClient(settings=settings)
    recording = RecordingSDK()
    client._client = recording

    result = client.contest_dispute("disp_NkQ8vRt2mWxYz1", {"summary": "x"})

    assert result.submitted is False
    assert result.response is None
    assert recording.dispute.calls == [], "nothing may reach the SDK"
    assert result.would_be_payload["body"] == {"summary": "x"}


@pytest.mark.parametrize(
    "dispute_id",
    [
        "disp_synthetic_0001",
        "disp_manual_0001",
        "disp_NkQ8vRt2mWxYz1",
        "anything_at_all",
        "",
    ],
)
def test_no_dispute_id_may_reach_razorpay(dispute_id):
    """Section 3: this system never ingests a real Razorpay dispute, so the set of ids
    permitted to touch the live workflow is empty by construction."""
    assert may_reach_razorpay(dispute_id) is False


@pytest.mark.parametrize("action", ["fetch", "accept", "contest"])
def test_every_dispute_action_is_blocked_for_a_locally_created_id(settings, action):
    client = RazorpayClient(settings=settings)
    recording = RecordingSDK()
    client._client = recording

    result = client._dispute_call(action, "disp_manual_0001", {"summary": "x"})

    assert result.submitted is False
    assert recording.dispute.calls == []
    assert "locally created" in result.reason


# -- payload construction ------------------------------------------------------------


def test_build_contest_payload_shape():
    payload = build_contest_payload(
        dispute_id="disp_synthetic_0001",
        amount_paise=249900,
        packet_text="The evidence establishes delivery.",
        evidence_refs=["pod_123", "otp_456"],
    )
    assert payload["amount"] == 249900
    assert payload["summary"] == "The evidence establishes delivery."
    assert payload["shipping_proof"] == ["pod_123", "otp_456"]
    assert "NOT transmitted" in payload["_recourse_note"]


def test_build_contest_payload_handles_no_evidence_refs():
    payload = build_contest_payload(
        dispute_id="disp_synthetic_0002", amount_paise=1000, packet_text="x", evidence_refs=[]
    )
    assert payload["shipping_proof"] is None
