"""Streamlit UI for the Travel Itinerary Planner Agent.

Launch with:
    streamlit run app.py

Flow:
  1. User types in chat box.
  2. Extractor pulls a candidate TripBrief out of the message.
  3. Pydantic validates it.
       - PASS: agent runs immediately, trace streams into chat.
       - FAIL: a clarification form is rendered with whatever was
         extracted pre-filled. Only after the user supplies missing
         fields does the agent loop start.
  4. Subsequent messages are treated as revisions (patch + merge) unless
     they name a new destination, in which case the brief is rebuilt
     from scratch and the previous itinerary is dropped.
"""

from __future__ import annotations

import json
import os
from datetime import date as dt_date
from typing import Optional

import streamlit as st

import tools as tools_mod
from agent import run_agent
from extractor import (
    extract_brief,
    extract_patch,
    is_destination_change,
    merge_patch,
    patch_is_empty,
    validate_brief,
)
from gemini_client import GeminiClient
from models import (
    AgentEvent,
    Currency,
    Itinerary,
    Message,
    Pace,
    TravelRequest,
    TripBrief,
)


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Travel Itinerary Agent",
    page_icon="✈️",
    layout="wide",
)

CONV_TURN_CAP = 10


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "conversation_history": [],
    "previous_itinerary": None,
    "current_brief": None,        # last successfully validated TripBrief
    "last_events": [],
    # Clarification-form state
    "pending_extracted": None,    # dict pre-filling the form
    "pending_message": None,      # original user message
    "pending_errors": [],         # list[FieldError]
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _reset_session() -> None:
    st.session_state.conversation_history = []
    st.session_state.previous_itinerary = None
    st.session_state.current_brief = None
    st.session_state.last_events = []
    st.session_state.pending_extracted = None
    st.session_state.pending_message = None
    st.session_state.pending_errors = []


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


REASONING_ICONS = {
    "LOOKUP": "🔍",
    "ARITHMETIC": "➗",
    "SPATIAL": "🗺️",
    "PREFERENCE_MATCH": "❤️",
    "CONSTRAINT_CHECK": "✔️",
    "PLANNING": "🧩",
    "CLARIFICATION": "❓",
}


def render_event(event: AgentEvent) -> None:
    kind = event.kind
    p = event.payload

    if kind == "start":
        st.caption("▶️ Agent starting on validated brief")
        with st.expander("Brief sent to agent", expanded=False):
            st.json(p.get("brief", {}))

    elif kind == "think":
        icon = REASONING_ICONS.get(p["reasoning_type"], "💭")
        with st.container(border=True):
            st.markdown(f"{icon} **THINK** — `{p['reasoning_type']}`")
            st.write(p["content"])

    elif kind == "tool_call":
        with st.container(border=True):
            st.markdown(f"🔧 **TOOL_CALL** — `{p['tool_name']}`")
            st.code(json.dumps(p["args"], indent=2), language="json")

    elif kind == "tool_result":
        with st.expander(f"⬅️ Result from `{p['tool_name']}`", expanded=False):
            st.code(json.dumps(p["result"], indent=2, default=str), language="json")

    elif kind == "final_answer":
        st.success("✅ **FINAL_ANSWER** — itinerary produced.")

    elif kind == "parse_error":
        with st.container(border=True):
            st.warning(
                f"⚠️ Parse error (retries left: {p['retries_left']}). "
                "Sending corrective message to the model."
            )
            with st.expander("Raw model output"):
                st.code(p["raw"], language="json")
            st.caption(p["error"][:300])

    elif kind == "max_iterations":
        st.error(f"❌ Hit max iterations ({p['max']}).")

    elif kind == "error":
        st.error(f"❌ {p.get('detail', 'Unknown error')}")


def render_itinerary(it: Itinerary) -> None:
    st.markdown(f"## 🗺️ {it.destination}")
    cols = st.columns(4)
    cols[0].metric("Start", it.start_date)
    cols[1].metric("Duration", f"{it.duration_days} days")
    cols[2].metric("Travelers", it.num_travelers)
    cols[3].metric("Confidence", it.confidence.value.title())

    bs = it.budget_summary
    st.markdown("### 💰 Budget")
    bcols = st.columns(3)
    bcols[0].metric("Total cost", f"{bs.total_cost:,.0f} {bs.currency}")
    if bs.budget_provided is not None:
        bcols[1].metric("Budget", f"{bs.budget_provided:,.0f} {bs.currency}")
    if bs.budget_remaining is not None:
        bcols[2].metric(
            "Remaining",
            f"{bs.budget_remaining:,.0f} {bs.currency}",
            delta=None if bs.budget_remaining >= 0 else "Over budget",
            delta_color="inverse" if bs.budget_remaining < 0 else "normal",
        )
    if bs.per_category:
        with st.expander("By category"):
            st.json(bs.per_category)

    if it.revision_summary:
        st.info(f"📝 Revision: {it.revision_summary}")

    st.markdown("### 📅 Days")
    if it.days:
        tabs = st.tabs([f"Day {d.day_number} — {d.date}" for d in it.days])
        for tab, day in zip(tabs, it.days):
            with tab:
                st.markdown(f"**Theme:** {day.theme}")
                for a in day.activities:
                    cost_str = f"{a.est_cost_per_person:,.0f} {a.currency}/person"
                    st.markdown(
                        f"- **{a.time}** — *{a.name}* "
                        f"({a.category}, {a.duration_minutes} min, {cost_str})"
                    )
                    if a.notes:
                        st.caption(a.notes)

    st.markdown("### 🛂 Self-checks")
    if it.self_checks:
        cols = st.columns(len(it.self_checks))
        for col, c in zip(cols, it.self_checks):
            with col:
                icon = "✅" if c.passed else "❌"
                st.markdown(f"{icon} **{c.name}**")
                st.caption(c.detail)

    if it.assumptions:
        with st.expander("📌 Assumptions"):
            for a in it.assumptions:
                st.markdown(f"- {a}")
    if it.open_questions:
        with st.expander("❓ Open questions", expanded=True):
            for q in it.open_questions:
                st.markdown(f"- {q}")


# ---------------------------------------------------------------------------
# Agent execution helper
# ---------------------------------------------------------------------------


def execute_agent_run(
    brief: TripBrief,
    original_message: str,
    client: GeminiClient,
    max_iter: int,
) -> None:
    """Run the agent loop, streaming events into the current container.

    Updates session state (conversation_history, previous_itinerary,
    current_brief) when finished.
    """
    request = TravelRequest(
        brief=brief,
        original_message=original_message,
        conversation_history=st.session_state.conversation_history[-CONV_TURN_CAP:],
        previous_itinerary=st.session_state.previous_itinerary,
    )

    trace_tab, raw_tab = st.tabs(["🧠 Live trace", "🗂 Raw events"])
    with trace_tab:
        trace_container = st.container()

    events: list[AgentEvent] = []
    final_itinerary: Optional[Itinerary] = None

    with st.spinner("Agent thinking…"):
        for event in run_agent(request, client, max_iterations=max_iter):
            events.append(event)
            with trace_container:
                render_event(event)
            if event.kind == "final_answer":
                final_itinerary = Itinerary.model_validate(event.payload["itinerary"])

    with raw_tab:
        st.json([e.model_dump() for e in events])

    # Persist
    st.session_state.last_events = [e.model_dump() for e in events]
    st.session_state.current_brief = brief
    st.session_state.conversation_history.append(
        Message(role="user", content=original_message)
    )

    if final_itinerary is not None:
        st.session_state.previous_itinerary = final_itinerary
        st.markdown("---")
        render_itinerary(final_itinerary)
        summary = (
            f"Generated {final_itinerary.duration_days}-day itinerary for "
            f"{final_itinerary.destination} "
            f"({final_itinerary.budget_summary.total_cost:,.0f} "
            f"{final_itinerary.budget_summary.currency})."
        )
        st.session_state.conversation_history.append(
            Message(role="agent", content=summary)
        )
    else:
        st.session_state.conversation_history.append(
            Message(role="agent", content="(Agent did not produce a final itinerary.)")
        )


# ---------------------------------------------------------------------------
# Clarification form
# ---------------------------------------------------------------------------


def render_clarification_form(api_key: str, model: str, max_iter: int) -> None:
    """Render a form to fill in the fields the extractor couldn't get.

    On submit: build a TripBrief, validate, and run the agent inline.
    """
    pending_msg = st.session_state.pending_message or ""
    extracted = st.session_state.pending_extracted or {}
    errors = st.session_state.pending_errors or []

    with st.chat_message("user"):
        st.write(pending_msg)

    with st.chat_message("assistant"):
        st.warning(
            "I need a bit more info before I can plan this trip. "
            "Please confirm or fill in the fields below."
        )
        if errors:
            with st.expander("What was missing or invalid", expanded=False):
                for err in errors:
                    st.markdown(f"- **`{err.field}`** — {err.message}")

        # Field defaults
        dest_default = extracted.get("destination") or ""

        sd_default = None
        sd_raw = extracted.get("start_date")
        if sd_raw:
            try:
                sd_default = dt_date.fromisoformat(sd_raw)
            except Exception:
                sd_default = None

        dur_default = int(extracted.get("duration_days") or 3)
        trav_default = int(extracted.get("num_travelers") or 1)
        budget_default = float(extracted.get("budget_amount") or 0.0)

        currencies = [c.value for c in Currency]
        cur_extracted = extracted.get("budget_currency")
        cur_idx = currencies.index(cur_extracted) if cur_extracted in currencies else 0

        interests_default = ", ".join(extracted.get("interests") or [])
        avoid_default = ", ".join(extracted.get("avoid") or [])

        paces = [p.value for p in Pace]
        pace_extracted = extracted.get("pace")
        pace_idx = paces.index(pace_extracted) if pace_extracted in paces else 1

        hours_default = int(extracted.get("max_daily_hours") or 14)

        with st.form("clarification_form"):
            c1, c2 = st.columns(2)
            with c1:
                dest = st.text_input("Destination *", value=dest_default)
                start_date = st.date_input(
                    "Start date *", value=sd_default or dt_date.today()
                )
                duration = st.number_input(
                    "Duration (days) *",
                    min_value=1, max_value=30,
                    value=max(1, min(30, dur_default)),
                )
                travelers = st.number_input(
                    "Travelers *",
                    min_value=1, max_value=20,
                    value=max(1, min(20, trav_default)),
                )
            with c2:
                budget_amount = st.number_input(
                    "Budget amount *",
                    min_value=0.0,
                    value=budget_default,
                    step=100.0,
                )
                budget_currency = st.selectbox("Currency *", currencies, index=cur_idx)
                pace = st.selectbox("Pace", paces, index=pace_idx)
                max_hours = st.number_input(
                    "Max daily hours",
                    min_value=4, max_value=16, value=hours_default,
                )

            interests = st.text_input(
                "Interests (comma-separated)", value=interests_default
            )
            avoid = st.text_input("Avoid (comma-separated)", value=avoid_default)

            bc1, bc2 = st.columns(2)
            with bc1:
                submitted = st.form_submit_button("✈️ Plan trip", use_container_width=True)
            with bc2:
                cancelled = st.form_submit_button("✖ Cancel", use_container_width=True)

        if cancelled:
            st.session_state.conversation_history.append(
                Message(role="user", content=pending_msg)
            )
            st.session_state.conversation_history.append(
                Message(role="agent", content="(Cancelled - tell me about your trip when ready.)")
            )
            st.session_state.pending_extracted = None
            st.session_state.pending_message = None
            st.session_state.pending_errors = []
            st.rerun()

        if submitted:
            form_data = {
                "destination": dest.strip(),
                "start_date": start_date.isoformat(),
                "duration_days": int(duration),
                "num_travelers": int(travelers),
                "budget_amount": float(budget_amount),
                "budget_currency": budget_currency,
                "interests": [s.strip() for s in interests.split(",") if s.strip()],
                "avoid": [s.strip() for s in avoid.split(",") if s.strip()],
                "pace": pace,
                "max_daily_hours": int(max_hours),
            }
            brief, error_resp = validate_brief(form_data)
            if brief is None:
                msgs = "; ".join(f"{e.field}: {e.message}" for e in (error_resp.errors or []))
                st.error(f"Still invalid — {msgs or 'unknown error'}")
                st.session_state.pending_extracted = form_data
            else:
                st.session_state.pending_extracted = None
                st.session_state.pending_message = None
                st.session_state.pending_errors = []
                try:
                    client = GeminiClient(api_key=api_key, model=model)
                except Exception as e:
                    st.error(f"Could not initialise Gemini client: {e}")
                    return
                execute_agent_run(brief, pending_msg, client, max_iter)


# ---------------------------------------------------------------------------
# New-message handler (extraction + decision)
# ---------------------------------------------------------------------------


def handle_new_message(
    user_input: str, api_key: str, model: str, max_iter: int
) -> None:
    """Process a fresh chat-input submission."""
    try:
        client = GeminiClient(api_key=api_key, model=model)
    except Exception as e:
        st.error(f"Could not initialise Gemini client: {e}")
        return

    with st.chat_message("user"):
        st.write(user_input)

    current_brief: Optional[TripBrief] = st.session_state.current_brief

    with st.chat_message("assistant"):
        with st.status("Parsing your request…", expanded=True) as status:
            try:
                if current_brief is not None:
                    st.caption("Treating as revision: extracting patch…")
                    patch = extract_patch(user_input, current_brief, client)
                    st.json(patch)

                    if is_destination_change(patch, current_brief):
                        st.caption(
                            f"Destination changed "
                            f"({current_brief.destination} → {patch['destination']}). "
                            "Starting fresh extraction."
                        )
                        st.session_state.previous_itinerary = None
                        extracted = extract_brief(user_input, client)
                        st.json(extracted)
                    elif patch_is_empty(patch):
                        status.update(state="error", label="No changes detected")
                        st.warning(
                            "I didn't catch any changes in your message. "
                            "What would you like to revise?"
                        )
                        return
                    else:
                        extracted = merge_patch(current_brief, patch)
                else:
                    st.caption("New trip: extracting parameters…")
                    extracted = extract_brief(user_input, client)
                    st.json(extracted)
            except Exception as e:
                status.update(state="error", label="Extraction failed")
                st.error(f"Could not parse your message: {e}")
                return

            brief, error_resp = validate_brief(extracted)
            if brief is None:
                status.update(state="error", label="Validation failed")
                missing = ", ".join(error_resp.missing_fields) or "see details"
                st.warning(f"Missing or invalid: {missing}")
                st.session_state.pending_extracted = error_resp.extracted or extracted
                st.session_state.pending_message = user_input
                st.session_state.pending_errors = error_resp.errors
                st.rerun()
            else:
                status.update(state="complete", label="✅ Parameters validated")

        execute_agent_run(brief, user_input, client, max_iter)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ Settings")

    api_key = st.text_input(
        "Gemini API key",
        type="password",
        value=os.getenv("GEMINI_API_KEY", ""),
        help="From https://aistudio.google.com/apikey",
    )
    model = st.selectbox(
        "Model",
        ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        index=0,
    )
    max_iter = st.slider("Max agent iterations", 5, 40, 25)

    st.divider()
    st.caption("**Demo toggles**")
    tools_mod.SIMULATE_WEATHER_FAILURE = st.checkbox(
        "Simulate weather tool failures",
        value=False,
    )

    st.divider()
    if st.button("🗑️ Reset session", use_container_width=True):
        _reset_session()
        st.rerun()

    st.divider()
    if st.session_state.current_brief is not None:
        with st.expander("📝 Current brief", expanded=False):
            st.json(st.session_state.current_brief.model_dump(mode="json"))

    with st.expander("ℹ️ Rubric mapping"):
        st.markdown(
            """
- **Explicit reasoning** — THINK steps, prompt §2
- **Structured I/O** — Pydantic `TripBrief` + `Itinerary`
- **Tool separation** — THINK vs TOOL_CALL split
- **Conversation loop** — revision protocol, prompt §6
- **Instructional framing** — worked example, prompt §8
- **Self-checks** — 5 mandatory checks, prompt §5
- **Reasoning-type awareness** — tagged enum
- **Fallbacks** — pre-flight validation form, prompt §7
- **Clarity** — numbered sections, hard rules §9
            """
        )

    with st.expander("🧰 Available tools"):
        for name, fn in tools_mod.TOOLS.items():
            doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
            st.markdown(f"**`{name}`** — {doc}")


# ---------------------------------------------------------------------------
# Main pane
# ---------------------------------------------------------------------------

st.title("✈️ Travel Itinerary Planner Agent")
st.caption(
    "Multi-step ReAct agent. Pre-flight validation gates the loop: "
    "if the message is missing required fields, a form appears before "
    "any LLM tokens are spent on planning. Supports Kyoto, Paris and Goa."
)

with st.expander("💡 Example prompts"):
    st.markdown(
        """
**Complete (skips the form):**
- *Plan a 4-day Kyoto trip starting 2026-04-05 for 2 travelers, ¥80,000 budget, we love temples and food.*
- *Plan 3 days in Paris starting 2026-10-12 for a couple, €600 budget, art and good food.*

**Incomplete (triggers the clarification form):**
- *Plan a trip to Kyoto, we love temples.*  (missing dates, duration, travelers, budget)
- *4 days in Paris with my partner.*  (missing date, budget)

**After a plan exists:**
- *Make it 3 days instead.*
- *Drop the museums.*
- *Actually, change destination to Goa.*  ← triggers a brand-new plan
        """
    )

# Replay conversation history
for m in st.session_state.conversation_history:
    with st.chat_message("user" if m.role == "user" else "assistant"):
        st.write(m.content)

# Current itinerary expander
if st.session_state.previous_itinerary is not None:
    with st.expander("📋 Current itinerary", expanded=False):
        render_itinerary(st.session_state.previous_itinerary)

# Branch: pending clarification form vs. chat input
if st.session_state.pending_extracted is not None:
    if not api_key:
        st.error("Please set your Gemini API key in the sidebar.")
        st.stop()
    render_clarification_form(api_key, model, max_iter)
else:
    user_input = st.chat_input("Describe your trip or revise the current plan…")
    if user_input:
        if not api_key:
            st.error("Please set your Gemini API key in the sidebar.")
            st.stop()
        handle_new_message(user_input, api_key, model, max_iter)
