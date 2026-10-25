"""PitchMind data contracts.

Every message that crosses a service boundary (Event Hubs, Web PubSub, HTTP)
is one of the models below. Pydantic is the source of truth; JSON Schema and
TypeScript types are generated from it (``python -m pitchmind_contracts.generate``).

Conventions
-----------
* ``t`` is seconds of play since kick-off: continuous, strictly non-decreasing,
  includes stoppage time, excludes the half-time break. The second half starts
  at whatever ``t`` the first half ended.
* ``minute`` is the broadcast minute. In the first half a value above 45 is
  stoppage time (display ``46`` as ``45+1``); in the second half above 90 likewise.
* Pitch is 105 x 68 metres. Coordinates are relative to the acting team:
  it always attacks towards ``x = 105``. ``y = 0`` is that team's right touchline.
* Player ids are ``<H|A><shirt number>``, e.g. ``H10``, ``A1``.
* Event ids are integers, strictly increasing within a match.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    WithJsonSchema,
    computed_field,
    model_validator,
)

from .enums import (
    RTL_LANGUAGES,
    AgentName,
    EventSource,
    EventType,
    InsightKind,
    Language,
    MetricName,
    MomentKind,
    Outcome,
    OverlaySlot,
    Persona,
    Phase,
    Position,
    TeamSide,
)

SCHEMA_VERSION = "1.0"

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0

PlayerId = Annotated[str, Field(pattern=r"^[HA]\d{1,2}$", examples=["H10", "A1"])]
EventId = Annotated[int, Field(ge=0)]
MatchClock = Annotated[float, Field(ge=0, description="Seconds of play since kick-off (continuous)")]
Minute = Annotated[int, Field(ge=0, le=130)]
Unit = Annotated[float, Field(ge=0, le=1)]
Point = Annotated[
    tuple[
        Annotated[float, Field(ge=0, le=PITCH_LENGTH_M)],
        Annotated[float, Field(ge=0, le=PITCH_WIDTH_M)],
    ],
    # Plain array form so TypeScript generators emit [number, number].
    WithJsonSchema(
        {"type": "array", "items": {"type": "number", "minimum": 0}, "minItems": 2, "maxItems": 2,
         "description": "[x, y] in metres, acting team attacks towards x = 105"}
    ),
]


class ContractModel(BaseModel):
    # Defaults are always serialized, so mark them required for consumers (TS `msg` is not optional).
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_serialization_defaults_required=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        # Computed fields are serialized for consumers; ignore them when parsing back.
        if isinstance(data, dict) and cls.model_computed_fields:
            return {k: v for k, v in data.items() if k not in cls.model_computed_fields}
        return data


# ---------------------------------------------------------------------------
# Match metadata
# ---------------------------------------------------------------------------


class PlayerAttributes(ContractModel):
    pace: Annotated[int, Field(ge=1, le=99)]
    passing: Annotated[int, Field(ge=1, le=99)]
    finishing: Annotated[int, Field(ge=1, le=99)]
    dribbling: Annotated[int, Field(ge=1, le=99)]
    defending: Annotated[int, Field(ge=1, le=99)]
    stamina: Annotated[int, Field(ge=1, le=99)]


class Player(ContractModel):
    id: PlayerId
    name: str
    short_name: str
    number: Annotated[int, Field(ge=1, le=99)]
    position: Position
    nationality: str
    attributes: PlayerAttributes


class TeamColors(ContractModel):
    primary: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
    secondary: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class Team(ContractModel):
    id: str
    name: str
    short_name: Annotated[str, Field(min_length=2, max_length=4)]
    side: TeamSide
    colors: TeamColors
    formation: Annotated[str, Field(pattern=r"^\d(-\d){2,4}$", examples=["4-3-3"])]
    players: list[Player]
    starting_xi: Annotated[list[PlayerId], Field(min_length=11, max_length=11)]

    @model_validator(mode="after")
    def _xi_in_squad(self) -> Self:
        squad = {p.id for p in self.players}
        missing = [pid for pid in self.starting_xi if pid not in squad]
        if missing:
            raise ValueError(f"starting_xi players not in squad: {missing}")
        prefix = "H" if self.side is TeamSide.HOME else "A"
        wrong = [p.id for p in self.players if not p.id.startswith(prefix)]
        if wrong:
            raise ValueError(f"{self.side} player ids must start with {prefix}: {wrong}")
        return self


class MatchMeta(ContractModel):
    msg: Literal["match_meta"] = "match_meta"
    schema_version: str = SCHEMA_VERSION
    match_id: str
    competition: str
    venue: str
    kickoff: datetime
    seed: int
    home: Team
    away: Team


# ---------------------------------------------------------------------------
# Stage 1 - Ingest
# ---------------------------------------------------------------------------


class MatchEvent(ContractModel):
    """One raw on-ball or off-ball event. Produced by the simulator or CV module."""

    msg: Literal["match_event"] = "match_event"
    schema_version: str = SCHEMA_VERSION
    id: EventId
    match_id: str
    t: MatchClock
    minute: Minute
    phase: Phase
    type: EventType
    team: TeamSide | None = None
    player: PlayerId | None = None
    receiver: PlayerId | None = Field(
        default=None, description="Pass receiver, or the player coming on for a substitution"
    )
    start: Point | None = None
    end: Point | None = None
    outcome: Outcome | None = None
    under_pressure: bool = False
    ball_speed_kmh: Annotated[float, Field(ge=0, le=200)] | None = None
    player_speed_kmh: Annotated[float, Field(ge=0, le=45)] | None = None
    distance_m: Annotated[float, Field(ge=0)] | None = Field(
        default=None, description="Carry/sprint distance, or pass length if precomputed"
    )
    related_event_id: EventId | None = None
    source: EventSource = EventSource.SIM

    @model_validator(mode="after")
    def _required_fields(self) -> Self:
        needs_actor = {
            EventType.PASS, EventType.CARRY, EventType.SHOT, EventType.TACKLE,
            EventType.INTERCEPTION, EventType.PRESSURE, EventType.SPRINT, EventType.GOAL,
        }
        if self.type in needs_actor and (self.player is None or self.team is None):
            raise ValueError(f"{self.type} events need team and player")
        if self.type in {EventType.PASS, EventType.CARRY, EventType.SHOT} and self.start is None:
            raise ValueError(f"{self.type} events need a start point")
        if self.type is EventType.PASS and self.outcome not in {Outcome.SUCCESS, Outcome.FAILURE}:
            raise ValueError("pass outcome must be success or failure")
        if self.type is EventType.SHOT and self.outcome not in {
            Outcome.ON_TARGET, Outcome.OFF_TARGET, Outcome.BLOCKED, Outcome.GOAL,
        }:
            raise ValueError("shot outcome must be on_target, off_target, blocked or goal")
        if self.type is EventType.CARD and self.outcome not in {Outcome.YELLOW, Outcome.RED}:
            raise ValueError("card outcome must be yellow or red")
        return self


# ---------------------------------------------------------------------------
# Stage 2 - Interpret
# ---------------------------------------------------------------------------


class Score(ContractModel):
    home: Annotated[int, Field(ge=0)] = 0
    away: Annotated[int, Field(ge=0)] = 0


class TeamStats(ContractModel):
    possession_pct: Annotated[float, Field(ge=0, le=100)]
    passes: Annotated[int, Field(ge=0)]
    pass_accuracy_pct: Annotated[float, Field(ge=0, le=100)]
    avg_pass_difficulty: Unit
    shots: Annotated[int, Field(ge=0)]
    shots_on_target: Annotated[int, Field(ge=0)]
    xg: Annotated[float, Field(ge=0)]
    xt: float
    tackles_won: Annotated[int, Field(ge=0)]
    pressure_index: Unit = Field(description="Rolling 5-min pressure applied in the opponent half")
    distance_covered_m: Annotated[float, Field(ge=0)]


class PlayerStats(ContractModel):
    player_id: PlayerId
    team: TeamSide
    touches: Annotated[int, Field(ge=0)]
    passes: Annotated[int, Field(ge=0)]
    pass_accuracy_pct: Annotated[float, Field(ge=0, le=100)]
    shots: Annotated[int, Field(ge=0)]
    xg: Annotated[float, Field(ge=0)]
    tackles_won: Annotated[int, Field(ge=0)]
    distance_covered_m: Annotated[float, Field(ge=0)]
    top_speed_kmh: Annotated[float, Field(ge=0, le=45)]
    sprints: Annotated[int, Field(ge=0)]


class StatSnapshot(ContractModel):
    """Full statistical state of the match, published on every meaningful change."""

    msg: Literal["stat_snapshot"] = "stat_snapshot"
    schema_version: str = SCHEMA_VERSION
    match_id: str
    t: MatchClock
    minute: Minute
    phase: Phase
    last_event_id: EventId
    score: Score
    home: TeamStats
    away: TeamStats
    momentum: Annotated[float, Field(ge=-1, le=1)] = Field(
        description="-1 = away dominating, +1 = home dominating"
    )
    control_chaos: Unit = Field(description="0 = calm, controlled; 1 = open, chaotic")
    rhythm_epm: Annotated[float, Field(ge=0)] = Field(description="Events per minute, last 5 min")
    players: list[PlayerStats]


# ---------------------------------------------------------------------------
# Stage 3 - Explain (deterministic part)
# ---------------------------------------------------------------------------


class Moment(ContractModel):
    """A moment that matters, detected by rules. Carries the facts the agents may use."""

    msg: Literal["moment"] = "moment"
    schema_version: str = SCHEMA_VERSION
    id: str
    match_id: str
    t: MatchClock
    minute: Minute
    kind: MomentKind
    importance: Unit
    team: TeamSide | None = None
    players: list[PlayerId] = []
    evidence: Annotated[list[EventId], Field(min_length=1)]
    metrics: dict[str, float] = Field(
        default_factory=dict,
        description="Facts agents may cite, e.g. {'pressure_index_before': 0.42, ...}",
    )
    fallback_text: str = Field(description="Deterministic English sentence used if agents fail")


# ---------------------------------------------------------------------------
# Stage 3/5 - Explain + Personalize (agent output)
# ---------------------------------------------------------------------------


class Segment(ContractModel):
    """An audience segment. Agents generate one insight variant per active segment."""

    persona: Persona
    language: Language
    club: TeamSide | None = None
    player: PlayerId | None = None
    metric_focus: MetricName | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        return (
            f"{self.persona}|{self.language}"
            f"|club:{self.club or '*'}|player:{self.player or '*'}"
            f"|metric:{self.metric_focus or '*'}"
        )

    @classmethod
    def from_key(cls, key: str) -> Segment:
        persona, language, club, player, metric = key.split("|")

        def part(raw: str, label: str) -> str | None:
            name, _, value = raw.partition(":")
            if name != label:
                raise ValueError(f"bad segment key part {raw!r}, expected {label}:...")
            return None if value == "*" else value

        return cls.model_validate(
            {
                "persona": persona,
                "language": language,
                "club": part(club, "club"),
                "player": part(player, "player"),
                "metric_focus": part(metric, "metric"),
            }
        )


class Claim(ContractModel):
    """One factual statement inside an insight, with the evidence that supports it."""

    text: str
    evidence: Annotated[list[EventId], Field(min_length=1)]
    metrics: dict[str, float] = {}


class Insight(ContractModel):
    msg: Literal["insight"] = "insight"
    schema_version: str = SCHEMA_VERSION
    id: str
    match_id: str
    moment_id: str | None = Field(default=None, description="None for recaps")
    t: MatchClock
    kind: InsightKind
    segment: Segment
    headline: Annotated[str, Field(max_length=90)]
    body: Annotated[str, Field(max_length=1500)]
    claims: list[Claim]
    verified: bool = Field(description="Passed the Verifier's evidence and number checks")
    fallback: bool = Field(default=False, description="Template text used instead of an LLM")
    agent_trace: list[AgentName] = Field(description="Agents that handled this insight, in order")
    model: str | None = None
    latency_ms: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _claims_unless_fallback(self) -> Self:
        if not self.fallback and not self.claims:
            raise ValueError("non-fallback insights must carry at least one evidenced claim")
        return self


# ---------------------------------------------------------------------------
# Stage 4 - Render
# ---------------------------------------------------------------------------


class OverlayMetric(ContractModel):
    name: MetricName
    value: float
    unit: str | None = None
    label: str | None = None


class Overlay(ContractModel):
    """A timed graphic for the broadcast overlay page or the second-screen app."""

    msg: Literal["overlay"] = "overlay"
    schema_version: str = SCHEMA_VERSION
    overlay_id: str
    match_id: str
    insight_id: str | None = None
    show_at: MatchClock
    duration_s: Annotated[float, Field(gt=0, le=60)]
    slot: OverlaySlot
    priority: Annotated[int, Field(ge=0, le=100)]
    segment_key: str
    language: Language
    title: Annotated[str, Field(max_length=60)]
    body: Annotated[str, Field(max_length=600)]
    team: TeamSide | None = None
    player_id: PlayerId | None = None
    metric: OverlayMetric | None = None
    evidence: list[EventId] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rtl(self) -> bool:
        return self.language in RTL_LANGUAGES


# ---------------------------------------------------------------------------
# Fans
# ---------------------------------------------------------------------------


class FanProfile(ContractModel):
    id: str
    display_name: str
    persona: Persona = Persona.CASUAL
    language: Language = Language.EN
    club: TeamSide | None = None
    player: PlayerId | None = None
    metric_focus: MetricName | None = None

    def to_segment(self) -> Segment:
        return Segment(
            persona=self.persona,
            language=self.language,
            club=self.club,
            player=self.player,
            metric_focus=self.metric_focus,
        )


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

WireMessage = Annotated[
    MatchMeta | MatchEvent | StatSnapshot | Moment | Insight | Overlay,
    Field(discriminator="msg"),
]

wire_adapter: TypeAdapter[WireMessage] = TypeAdapter(WireMessage)


def parse_wire(raw: str | bytes) -> MatchMeta | MatchEvent | StatSnapshot | Moment | Insight | Overlay:
    """Parse any JSON message from a bus or socket into its contract model."""
    return wire_adapter.validate_json(raw)
