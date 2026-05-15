# Travel Itinerary Planner Agent

A multi-step ReAct-style agent built on the Gemini API. Designed so its
**system prompt** scores well on this evaluation rubric:

> explicit reasoning · structured output · tool/reasoning separation ·
> conversation loop · instructional framing · self-checks ·
> reasoning-type awareness · fallbacks · overall clarity

The agent plans day-by-day travel itineraries using mocked tools, supports
multi-turn revisions, and switches to a fresh plan if you change destination.

---

## Project layout

```
travel_agent/
├── app.py             # Streamlit UI - launch this
├── agent.py           # The agent loop (generator yielding AgentEvents)
├── extractor.py       # Pre-flight: free text → validated TripBrief
├── gemini_client.py   # Thin wrapper around google-genai
├── prompts.py         # System prompts (main + extractor + revision extractor)
├── models.py          # Pydantic models for input, output, and steps
├── tools.py           # Mocked tools (weather, distance, currency, POIs)
├── requirements.txt
└── README.md
```

---

## Setup

```bash
# 1. (optional) create a venv
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows

# 2. install deps
pip install -r requirements.txt

# 3. set your Gemini API key
export GEMINI_API_KEY="your-key-from-aistudio.google.com/apikey"

# 4. run the UI
streamlit run app.py
```

You can also paste the API key into the sidebar instead of exporting it.

---

## Demo flow

The agent supports three destinations via mocked POI data: **Kyoto**, **Paris**, **Goa**.

1. **Initial plan**  
   *"Plan a 4-day Kyoto trip in early April, budget ¥80,000, 2 travelers, we love temples and food."*

2. **Revision (minimum perturbation)**  
   *"Make it 3 days."*  
   → the agent re-runs only the affected reasoning + self-checks; untouched days stay put.

3. **Brand-new plan (different destination)**  
   *"Actually, change destination to Goa."*  
   → the agent recognises the destination change and ignores the prior itinerary.

4. **Fallback demo**  
   In the sidebar, toggle **Simulate weather tool failures**. The agent will
   log the failure in a THINK step, fall back to a default assumption, and
   lower confidence accordingly.

5. **Constraint conflict demo**  
   *"Plan 1 day in Paris with 8 must-see museums on a €20 budget for 4 people."*  
   → the agent should surface the conflict in `open_questions` rather than
   silently violating the budget.

---

## How the loop works

Every chat message goes through two phases:

**Phase 1 — Pre-flight extraction & validation (`extractor.py`)**

1. The user's free-form text is sent to Gemini *once* with a tight, schema-only system prompt (`EXTRACTOR_SYSTEM_PROMPT`).
2. The result is validated against the strict `TripBrief` Pydantic model.
3. If validation **passes**, we proceed to phase 2.
4. If validation **fails**, the UI renders a clarification form pre-filled with whatever *was* extracted. The agent loop is **never reached** until every required field is present — no tokens wasted reasoning over a half-specified trip.

For revisions (when a previous brief exists), Gemini extracts only the *changed* fields (`REVISION_EXTRACTOR_SYSTEM_PROMPT`), they're merged into the current brief, and the merged result is re-validated. A destination change blows away `previous_itinerary` and re-extracts from scratch.

**Phase 2 — Agent loop (`agent.py`)**

Each iteration:

1. Build a `TravelRequest` carrying the validated `brief`, the original message, the conversation tail, and the previous itinerary.
2. Gemini emits **one** JSON step: `THINK`, `TOOL_CALL`, or `FINAL_ANSWER`.
3. The harness validates that JSON against the `AgentStep` discriminated union.
4. `TOOL_CALL` → execute mock tool, feed result back as a user message.
5. `FINAL_ANSWER` → validate against the `Itinerary` schema and render.
6. Parse failures send a corrective message back (capped at 2 retries).
7. Hard cap of `MAX_ITERATIONS = 25` prevents runaway loops.

---

## Rubric mapping

| Rubric criterion          | Where it lives                                                              |
|---------------------------|-----------------------------------------------------------------------------|
| Explicit reasoning        | `prompts.py` §2 — model must emit THINK steps; one step per response       |
| Structured output         | `prompts.py` §3 + `models.py` — JSON schemas, Pydantic validation         |
| Tool / reasoning split    | `prompts.py` §4 — THINK vs TOOL_CALL are separate step types               |
| Conversation loop         | `prompts.py` §6 + `agent.py` — revision protocol, history threading       |
| Instructional framing     | `prompts.py` §8 — compact worked example end-to-end                       |
| Internal self-checks      | `prompts.py` §5 — 5 mandatory checks; harness re-validates                |
| Reasoning-type awareness  | `models.py::ReasoningType` enum, enforced by Pydantic                     |
| Fallbacks                 | `prompts.py` §7 — missing input, tool failure, infeasible constraints     |
| Overall clarity           | Numbered sections, hard rules (§9), tight enum of step types              |

---

## Things you can grade-poke at

- Open `prompts.py` and try **removing** the reasoning-type tags or
  self-checks — re-run the rubric and watch the score drop.
- In the UI, the **Raw events** tab shows every `AgentEvent` as JSON for
  inspection.
- `models.py` is the single source of truth — if a model output doesn't
  match the schema, the harness retries.
