"""Pre-flight extractor & validator.

Sits between the chat box and the agent loop. Free-form user text is sent
to Gemini once with a tight schema-only prompt; the result is validated
against `TripBrief`. If validation fails, the harness returns a
`MissingFieldsResponse` and the UI shows a clarification form before any
agent loop is spent.
"""

from __future__ import annotations

from datetime import date as dt_date
from typing import Optional

from pydantic import ValidationError

from gemini_client import GeminiClient
from models import (
    FieldError,
    MissingFieldsResponse,
    TripBrief,
)
from prompts import EXTRACTOR_SYSTEM_PROMPT, REVISION_EXTRACTOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Extraction (LLM calls)
# ---------------------------------------------------------------------------


def extract_brief(user_message: str, client: GeminiClient) -> dict:
    """Free-form text → dict of extracted fields (nulls for missing).

    Returns the raw parsed JSON; it has NOT been validated against
    TripBrief yet. Pass to `validate_brief` next.
    """
    today = dt_date.today().isoformat()
    convo = [
        {
            "role": "user",
            "content": (
                f"Today is {today}.\n\n"
                f"User message:\n{user_message}\n\n"
                f"Extract trip parameters as JSON."
            ),
        }
    ]
    raw = client.generate_step(EXTRACTOR_SYSTEM_PROMPT, convo, temperature=0.0)
    return client.parse_json_step(raw)


def extract_patch(
    user_message: str, current: TripBrief, client: GeminiClient
) -> dict:
    """Revision text + current brief → dict of changed fields only."""
    today = dt_date.today().isoformat()
    convo = [
        {
            "role": "user",
            "content": (
                f"Today is {today}.\n\n"
                f"Current trip brief:\n{current.model_dump_json(indent=2)}\n\n"
                f"User's revision message:\n{user_message}\n\n"
                f"Return ONLY the fields that change."
            ),
        }
    ]
    raw = client.generate_step(REVISION_EXTRACTOR_SYSTEM_PROMPT, convo, temperature=0.0)
    return client.parse_json_step(raw)


# ---------------------------------------------------------------------------
# Validation (pure Python - no LLM)
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS = {
    "destination",
    "start_date",
    "duration_days",
    "num_travelers",
    "budget_amount",
    "budget_currency",
}


def _clean(extracted: dict) -> dict:
    """Drop nulls and empty strings so Pydantic raises 'missing' not 'wrong type'."""
    return {k: v for k, v in extracted.items() if v is not None and v != ""}


def validate_brief(
    extracted: dict,
) -> tuple[Optional[TripBrief], Optional[MissingFieldsResponse]]:
    """Try to build a TripBrief from an extracted dict.

    Returns (brief, None) on success or (None, error_response) on failure.
    """
    cleaned = _clean(extracted)
    try:
        brief = TripBrief(**cleaned)
        return brief, None
    except ValidationError as e:
        errors: list[FieldError] = []
        missing: list[str] = []
        for err in e.errors():
            field = ".".join(str(x) for x in err["loc"])
            errors.append(
                FieldError(
                    field=field,
                    message=err["msg"],
                    error_type=err.get("type", ""),
                )
            )
            if err.get("type") == "missing":
                missing.append(field)
        # Also include fields that weren't in the extracted dict at all
        for req in _REQUIRED_FIELDS:
            if req not in cleaned and req not in missing:
                missing.append(req)
        return None, MissingFieldsResponse(
            extracted=cleaned, errors=errors, missing_fields=missing
        )


# ---------------------------------------------------------------------------
# Revision helpers
# ---------------------------------------------------------------------------


def is_destination_change(patch: dict, current: TripBrief) -> bool:
    """Did the user ask for a different destination?"""
    new = (patch.get("destination") or "").strip().lower()
    if not new:
        return False
    cur = current.destination.strip().lower()
    if new == cur:
        return False
    # Loose containment to forgive "kyoto" vs "kyoto japan"
    return new not in cur and cur not in new


def merge_patch(current: TripBrief, patch: dict) -> dict:
    """Apply a non-null patch on top of the current brief, return a dict."""
    base = current.model_dump(mode="json")
    for k, v in patch.items():
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        base[k] = v
    return base


def patch_is_empty(patch: dict) -> bool:
    """True if the patch contains no actionable changes."""
    return not any(
        v is not None and not (isinstance(v, str) and v.strip() == "")
        for v in patch.values()
    )
