"""The agent loop.

`run_agent` is a generator that yields AgentEvents as the agent reasons,
calls tools, and finally emits a validated itinerary. The Streamlit UI
consumes these events to render the trace live.

Loop invariants:
  - One LLM call per iteration
  - LLM emits one of: THINK | TOOL_CALL | FINAL_ANSWER
  - TOOL_CALL → harness executes the tool and feeds the result back
  - FINAL_ANSWER → validate against Itinerary schema and return
  - On validation failure, send a corrective message and retry (capped)
  - Hard cap on total iterations to prevent runaway loops
"""

from __future__ import annotations

import json
from typing import Iterator

from pydantic import TypeAdapter, ValidationError

from gemini_client import GeminiClient
from models import (
    AgentEvent,
    AgentStep,
    FinalAnswerStep,
    Itinerary,
    ThinkStep,
    ToolCallStep,
    TravelRequest,
)
from prompts import SYSTEM_PROMPT
from tools import execute_tool


MAX_ITERATIONS = 25
MAX_PARSE_RETRIES = 2


_STEP_ADAPTER = TypeAdapter(AgentStep)


def _build_initial_user_message(request: TravelRequest) -> str:
    """Render the validated brief + prior state into a single user turn."""
    parts: list[str] = []

    parts.append("=== VALIDATED TRIP BRIEF (source of truth) ===")
    parts.append(request.brief.model_dump_json(indent=2))
    parts.append("")
    parts.append("=== ORIGINAL USER MESSAGE (for tone / extra hints) ===")
    parts.append(request.original_message)
    parts.append("")

    if request.conversation_history:
        parts.append("=== CONVERSATION HISTORY ===")
        for m in request.conversation_history:
            parts.append(f"[{m.role}] {m.content}")
        parts.append("")

    if request.previous_itinerary is not None:
        parts.append("=== PREVIOUS ITINERARY (for revision context) ===")
        parts.append(request.previous_itinerary.model_dump_json(indent=2))
        parts.append("")
        parts.append(
            "This is a revision. Apply MINIMUM PERTURBATION - keep "
            "untouched days as-is. Re-run all five self-checks on the "
            "whole updated plan. Populate revision_summary."
        )
        parts.append("")

    parts.append("Begin. Emit ONE JSON step.")
    return "\n".join(parts)


def run_agent(
    request: TravelRequest,
    client: GeminiClient,
    max_iterations: int = MAX_ITERATIONS,
) -> Iterator[AgentEvent]:
    """Run the agent loop, yielding events as they happen."""

    yield AgentEvent(
        kind="start",
        payload={
            "original_message": request.original_message,
            "brief": request.brief.model_dump(mode="json"),
        },
    )

    conversation: list[dict] = [
        {"role": "user", "content": _build_initial_user_message(request)}
    ]

    parse_retries_left = MAX_PARSE_RETRIES

    for iteration in range(max_iterations):
        # --- Call the LLM -------------------------------------------------
        try:
            raw = client.generate_step(SYSTEM_PROMPT, conversation)
        except Exception as e:
            yield AgentEvent(
                kind="error",
                payload={"detail": f"LLM call failed: {type(e).__name__}: {e}"},
            )
            return

        # --- Parse + validate --------------------------------------------
        try:
            raw_dict = client.parse_json_step(raw)
            step: AgentStep = _STEP_ADAPTER.validate_python(raw_dict)
        except (ValueError, ValidationError) as e:
            yield AgentEvent(
                kind="parse_error",
                payload={"raw": raw, "error": str(e), "retries_left": parse_retries_left},
            )
            if parse_retries_left <= 0:
                yield AgentEvent(kind="error", payload={"detail": "Out of parse retries."})
                return
            parse_retries_left -= 1
            # Record the bad reply and send a corrective nudge
            conversation.append({"role": "assistant", "content": raw})
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        "Your last reply was not valid JSON matching the required "
                        "step schema. Re-emit a SINGLE JSON object matching exactly "
                        "one of THINK | TOOL_CALL | FINAL_ANSWER as described. "
                        f"Parser said: {e}"
                    ),
                }
            )
            continue

        # Successful parse - record the assistant turn verbatim
        conversation.append({"role": "assistant", "content": raw})

        # --- Dispatch on step type ---------------------------------------
        if isinstance(step, ThinkStep):
            yield AgentEvent(
                kind="think",
                payload={
                    "reasoning_type": step.reasoning_type.value,
                    "content": step.content,
                    "iteration": iteration,
                },
            )
            conversation.append({"role": "user", "content": "Continue with the next step."})

        elif isinstance(step, ToolCallStep):
            yield AgentEvent(
                kind="tool_call",
                payload={
                    "tool_name": step.tool_name,
                    "args": step.args,
                    "iteration": iteration,
                },
            )
            result = execute_tool(step.tool_name, step.args)
            yield AgentEvent(
                kind="tool_result",
                payload={
                    "tool_name": step.tool_name,
                    "args": step.args,
                    "result": result,
                    "iteration": iteration,
                },
            )
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        f"TOOL_RESULT for {step.tool_name}({json.dumps(step.args)}):\n"
                        f"{json.dumps(result, indent=2, default=str)}\n\n"
                        "Continue with the next step."
                    ),
                }
            )

        elif isinstance(step, FinalAnswerStep):
            yield AgentEvent(
                kind="final_answer",
                payload={
                    "itinerary": step.itinerary.model_dump(mode="json"),
                    "iteration": iteration,
                },
            )
            return

    yield AgentEvent(kind="max_iterations", payload={"max": max_iterations})
