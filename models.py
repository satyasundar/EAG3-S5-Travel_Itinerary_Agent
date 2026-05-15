"""Pydantic models for the Travel Itinerary Planner Agent.

All input and output flowing through the agent is validated against these
models. They are also the single source of truth for the schemas described
in the system prompt.
"""

from __future__ import annotations

from datetime import date as dt_date
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReasoningType(str, Enum):
    """The kind of thinking a THINK step represents.

    Tagging each reasoning step forces the model to be explicit about
    *what kind* of cognition it's doing, which the rubric rewards under
    'Reasoning Type Awareness'.
    """

    LOOKUP = "LOOKUP"  # Fetching factual info
    ARITHMETIC = "ARITHMETIC"  # Budget / time math
    SPATIAL = "SPATIAL"  # Routing, grouping by proximity
    PREFERENCE_MATCH = "PREFERENCE_MATCH"  # Matching POIs to user interests
    CONSTRAINT_CHECK = "CONSTRAINT_CHECK"  # Verifying against limits
    PLANNING = "PLANNING"  # Sequencing, composing days
    CLARIFICATION = "CLARIFICATION"  # Deciding to ask the user


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Currency(str, Enum):
    """Supported currencies for the trip budget.

    Limited to the set our mock convert_currency tool knows about.
    """

    INR = "INR"
    JPY = "JPY"
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"


class Pace(str, Enum):
    RELAXED = "relaxed"
    MODERATE = "moderate"
    PACKED = "packed"


# ---------------------------------------------------------------------------
# Validated trip brief - the structured input the agent actually runs on
# ---------------------------------------------------------------------------


class TripBrief(BaseModel):
    """Strict, validated trip parameters.

    The agent never runs on free-form text. The extractor parses the user's
    message into this shape, and Pydantic validation acts as a pre-flight
    gate: if any required field is missing or malformed, the UI shows a
    clarification form before any agent loop is spent.
    """

    # Required
    destination: str = Field(..., min_length=1, description="City/country name")
    start_date: dt_date = Field(..., description="ISO YYYY-MM-DD")
    duration_days: int = Field(..., ge=1, le=30)
    num_travelers: int = Field(..., ge=1, le=20)
    budget_amount: float = Field(..., gt=0)
    budget_currency: Currency

    # Optional - sensible defaults
    interests: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    pace: Pace = Pace.MODERATE
    max_daily_hours: int = Field(default=14, ge=4, le=16)


class FieldError(BaseModel):
    """One validation error, framed for UI display."""

    field: str
    message: str
    error_type: str = ""  # e.g. "missing", "value_error", "type_error"


class MissingFieldsResponse(BaseModel):
    """What the validator returns when a TripBrief can't be built.

    `extracted` carries whatever WAS extracted (so the form can pre-fill).
    """

    extracted: dict = Field(default_factory=dict)
    errors: list[FieldError] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Conversation / Input
# ---------------------------------------------------------------------------


class Message(BaseModel):
    role: Literal["user", "agent"]
    content: str


class TravelRequest(BaseModel):
    """Input to a single run of the agent.

    `brief` is the validated source of truth. `original_message` is kept
    for context (the agent may benefit from seeing the user's tone or
    extra hints that didn't make it into structured fields).
    """

    brief: TripBrief
    original_message: str
    conversation_history: list[Message] = Field(default_factory=list)
    previous_itinerary: Optional["Itinerary"] = None


# ---------------------------------------------------------------------------
# Itinerary (the user-facing output)
# ---------------------------------------------------------------------------


class Activity(BaseModel):
    time: str  # "09:00"
    name: str
    category: str  # "temple", "food", "nature", ...
    poi_id: Optional[str] = None  # Reference to tool-returned POI
    duration_minutes: int
    est_cost_per_person: float
    currency: str
    notes: str = ""


class DayPlan(BaseModel):
    day_number: int
    date: str  # ISO "YYYY-MM-DD"
    theme: str  # e.g. "Eastern Kyoto temples & Gion evening"
    activities: list[Activity]


class BudgetSummary(BaseModel):
    total_cost: float  # for the whole group, in user's requested currency
    currency: str
    per_category: dict[str, float] = Field(default_factory=dict)
    budget_provided: Optional[float] = None
    budget_remaining: Optional[float] = None


class SelfCheckResult(BaseModel):
    name: str  # "budget_check", "time_check", ...
    passed: bool
    detail: str


class Itinerary(BaseModel):
    destination: str
    start_date: str
    duration_days: int
    num_travelers: int
    days: list[DayPlan]
    budget_summary: BudgetSummary
    self_checks: list[SelfCheckResult]
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: Confidence
    revision_summary: Optional[str] = None  # populated only on revisions


# Forward-ref resolution
TravelRequest.model_rebuild()


# ---------------------------------------------------------------------------
# Agent steps (the discriminated union the LLM emits one at a time)
# ---------------------------------------------------------------------------


class ThinkStep(BaseModel):
    step_type: Literal["THINK"] = "THINK"
    reasoning_type: ReasoningType
    content: str


class ToolCallStep(BaseModel):
    step_type: Literal["TOOL_CALL"] = "TOOL_CALL"
    tool_name: str
    args: dict


class FinalAnswerStep(BaseModel):
    step_type: Literal["FINAL_ANSWER"] = "FINAL_ANSWER"
    itinerary: Itinerary


AgentStep = Annotated[
    Union[ThinkStep, ToolCallStep, FinalAnswerStep],
    Field(discriminator="step_type"),
]


# ---------------------------------------------------------------------------
# Events the agent emits to the UI (for live display)
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    tool_name: str
    args: dict
    result: dict | list


class AgentEvent(BaseModel):
    """One observable thing the agent does, streamed to the UI."""

    kind: Literal[
        "start",
        "think",
        "tool_call",
        "tool_result",
        "final_answer",
        "parse_error",
        "max_iterations",
        "error",
    ]
    payload: dict = Field(default_factory=dict)
