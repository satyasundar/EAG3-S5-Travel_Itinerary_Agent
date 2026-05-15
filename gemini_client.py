"""Thin wrapper around the Gemini API.

Uses the `google-genai` SDK (the current Python SDK for the Gemini API).
We force JSON output via `response_mime_type` and pass system instruction
separately so the conversation `contents` only carries user/assistant turns.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from google import genai
from google.genai import types


# Strip ```json ... ``` and stray prose around a JSON object, just in case.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _extract_json(text: str) -> str:
    """Best-effort: pull the first {...} block out of `text`."""
    text = _FENCE_RE.sub("", text).strip()
    # If it already starts with { we're done.
    if text.startswith("{"):
        return text
    # Otherwise find the first balanced JSON object.
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


class GeminiClient:
    """Wraps a single Gemini conversation."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate_step(
        self,
        system_prompt: str,
        conversation: list[dict],
        temperature: float = 0.3,
    ) -> str:
        """Send one round and return the raw text reply.

        `conversation` is a list of {"role": "user"|"assistant", "content": str}.
        Gemini uses "user" and "model" - we translate.
        """
        contents = []
        for msg in conversation:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
            )

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=temperature,
            ),
        )
        return (response.text or "").strip()

    def parse_json_step(self, raw_text: str) -> dict:
        """Parse the LLM's reply as a JSON dict. Raises ValueError on failure."""
        candidate = _extract_json(raw_text)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Model output was not valid JSON.\nRaw output:\n{raw_text}\n\nParse error: {e}"
            ) from e
