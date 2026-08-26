"""LLM drafting providers for the representment packet.

Provider-pluggable by design. `draft_with_llm()` is the only entry point; it resolves a
provider from configuration, and ANY failure returns None so packet_generator falls back
to the deterministic template. A drafting failure must never lose a decision -- the
decision was already made by the NLI engine before this module is reached.

    gemini     google-genai. Preferred under LLM_PROVIDER=auto because the free tier
               means someone cloning this repo can exercise the LLM path without paying.
    anthropic  the anthropic SDK, as named in CLAUDE.md Section 3.
    none       template only. A supported configuration, not a broken one.

WHY THE MODEL NAME IS DISCOVERED, NOT HARD-CODED
Model identifiers change often enough that a pinned string is a liability -- a wrong one
fails at demo time with an opaque 404. If GEMINI_MODEL is unset, `resolve_gemini_model()`
lists what the key can actually see and picks the best match from a preference order. The
result is cached, so this costs one extra API call per process.

SCOPE (CLAUDE.md Section 3): an LLM is used ONLY to rewrite prose for a decision that has
already been made. Nothing here can change a recommendation, a verdict or a confidence.
The facts cited are fixed by the template that is passed in as grounding.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from app.config import get_settings
from app.models.schemas import ClaimVerdict, Dispute

logger = logging.getLogger("recourse.packet.llm")

# Preference order when discovering a Gemini model. Lite/fast variants first: this is a
# short prose-rewriting task, not reasoning -- the reasoning already happened in the NLI
# engine, and the facts are fixed by the template passed in as grounding.
#
# Ordering established by measurement against a live key, not by assumption:
#   gemini-flash-lite-latest   OK    0.8s
#   gemini-3.1-flash-lite      OK    0.9s
#   gemini-flash-latest        504  14.4s   (aliased endpoint was congested)
#   gemini-2.5-flash           404          (not served on this API version)
#   gemini-2.0-flash           404          (not served on this API version)
#
# That last pair is why the model is discovered rather than pinned: the identifiers a
# developer is most likely to hard-code from memory do not resolve at all.
GEMINI_MODEL_PREFERENCES = (
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite",
    "gemini-flash-latest",
    "gemini-3-flash",
    "gemini-2.5-flash",
    "gemini-pro-latest",
)

_resolved_gemini_model: Optional[str] = None

SYSTEM_PROMPT = (
    "You are a chargeback representment specialist writing to a card issuer on behalf of "
    "an Indian e-commerce merchant. You write in plain, factual, professional English. "
    "You are concise and you never overstate."
)

USER_PROMPT_TEMPLATE = """Rewrite the representment below as a clear, professional letter to the issuing bank.

STRICT RULES:
- Use ONLY facts that appear in the draft. Do not invent evidence, dates, names or references.
- Do not change, soften or strengthen the stated confidence figures.
- Do not claim certainty the draft does not claim.
- Keep every source reference (ref: ...) exactly as written.
- Aim for 200-320 words. No markdown, no bullet characters, no headings in title case.
- End with the requested outcome.

DISPUTE CONTEXT
Reason code: {reason_code}
Amount: Rs {amount:,.2f}
The bank's claim: {claim_text}

DRAFT TO REWRITE
{template}
"""


def resolve_gemini_model(client, configured: str = "") -> Optional[str]:
    """Return a usable Gemini model id, discovering one if not configured."""
    global _resolved_gemini_model
    if configured:
        return configured
    if _resolved_gemini_model:
        return _resolved_gemini_model

    try:
        available = []
        for model in client.models.list():
            name = (getattr(model, "name", "") or "").removeprefix("models/")
            actions = getattr(model, "supported_actions", None) or []
            # Some SDK versions omit supported_actions; treat that as "probably usable".
            if not actions or "generateContent" in actions:
                available.append(name)
    except Exception as exc:
        logger.warning("could not list Gemini models (%s); trying preference order blind", exc)
        available = []

    for preferred in GEMINI_MODEL_PREFERENCES:
        for name in available:
            if name == preferred or name.startswith(preferred):
                _resolved_gemini_model = name
                logger.info("resolved Gemini model: %s", name)
                return name

    # Nothing matched the preference list: take any flash/pro model we can see.
    for name in available:
        if "flash" in name or "pro" in name:
            _resolved_gemini_model = name
            logger.info("resolved Gemini model (fallback): %s", name)
            return name

    if available:
        _resolved_gemini_model = available[0]
        return available[0]

    logger.warning("no Gemini models visible to this key")
    return None


def _draft_with_gemini(prompt: str) -> Optional[str]:
    from google import genai
    from google.genai import types

    settings = get_settings()
    timeout_ms = int(settings.llm_timeout_seconds * 1000)

    # Bound the whole attempt. Observed in testing: a 503 "model is experiencing high
    # demand" left the SDK retrying with exponential backoff for 296 SECONDS before
    # raising, which hung /decide for five minutes. The fallback was correct but far too
    # slow to be useful. A fallback that is not fast is not graceful.
    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(
                attempts=settings.llm_retry_attempts,
                initial_delay=0.5,
                max_delay=2.0,
            ),
        ),
    )

    model = resolve_gemini_model(client, settings.gemini_model)
    if not model:
        return None

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,  # low: this is factual rewriting, not creative writing
            max_output_tokens=1200,
            # We pass no tools; leaving AFC on makes the SDK emit a warning and adds
            # needless machinery to a plain text call.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return (response.text or "").strip() or None


def _draft_with_anthropic(prompt: str) -> Optional[str]:
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_retry_attempts,
    )
    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1200,
        temperature=0.3,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    return text.strip() or None


def draft_with_llm(
    dispute: Dispute,
    verdicts: Sequence[ClaimVerdict],
    template: str,
) -> Optional[str]:
    """Rewrite the template packet using the configured LLM provider.

    Returns None on any failure or when no provider is configured, so the caller keeps the
    deterministic template. Never raises.
    """
    settings = get_settings()
    provider = settings.resolve_llm_provider()
    if provider == "none":
        return None

    prompt = USER_PROMPT_TEMPLATE.format(
        reason_code=dispute.reason_code,
        amount=dispute.amount / 100,
        claim_text=dispute.claim_text,
        template=template,
    )

    try:
        if provider == "gemini":
            drafted = _draft_with_gemini(prompt)
        elif provider == "anthropic":
            drafted = _draft_with_anthropic(prompt)
        else:
            return None
    except Exception as exc:
        logger.warning(
            "LLM drafting failed via %s for %s (%s); falling back to template",
            provider,
            dispute.dispute_id,
            exc,
        )
        return None

    if not drafted:
        return None

    # A returned draft that lost the source references has lost its evidentiary value;
    # the template is better than fluent prose that cites nothing.
    refs = [e.source_ref for e in dispute.evidence_bundle if e.source_ref]
    if refs and not any(ref in drafted for ref in refs):
        logger.warning(
            "%s: LLM draft dropped every source reference; keeping template",
            dispute.dispute_id,
        )
        return None

    logger.info("%s: packet drafted via %s (%d chars)", dispute.dispute_id, provider, len(drafted))
    return drafted


# Backwards-compatible alias: packet_generator imports this name.
draft_with_claude = draft_with_llm


__all__ = [
    "GEMINI_MODEL_PREFERENCES",
    "SYSTEM_PROMPT",
    "draft_with_llm",
    "resolve_gemini_model",
]
