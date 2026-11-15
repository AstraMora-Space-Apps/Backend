"""Strict Pydantic v2 schemas matching Frontend types.ts and API_ASSUMPTIONS.md."""

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
Platform = Literal["iss", "drop_tower", "other"]
FuelClass = Literal["solid", "gas", "liquid"]
FlowDirection = Literal["opposed", "concurrent", "quiescent"]
Pillar = Literal["prevention", "detection", "suppression", "supporting"]
Strength = Literal["low", "medium", "high"]
RiskLevel = Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# Building Blocks
# ---------------------------------------------------------------------------
class RangeObj(BaseModel):
    """Inclusive numeric range where min <= max."""

    min: float
    max: float

    @model_validator(mode="after")
    def validate_min_max(self) -> "RangeObj":
        if self.min > self.max:
            raise ValueError(f"range.min ({self.min}) must be <= range.max ({self.max})")
        return self

    model_config = ConfigDict(extra="ignore")


class Citation(BaseModel):
    """Grounding citation linking a statement to a verified NASA paper/report."""

    paper_title: str = Field(min_length=1, description="Source paper or report title")
    investigation: str = Field(description="Investigation name (e.g. BASS-II)")
    page: Optional[int] = Field(default=None, description="Source page number or null")
    quote: str = Field(description="Verbatim source passage")
    source_url: Optional[str] = Field(default=None, description="Direct URL or null")

    model_config = ConfigDict(extra="ignore")


class Evidence(BaseModel):
    """Evidence metrics backing an answer or finding."""

    test_count: int = Field(ge=0, description="Total number of relevant experimental runs")
    platform: Platform = Field(description="Flight platform (iss, drop_tower, other)")
    repeats: int = Field(ge=0, description="Number of duplicate verification runs")
    strength: Strength = Field(description="Confidence classification (low, medium, high)")

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Ask Models
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    """Question payload for POST /ask."""

    question: str = Field(min_length=1, description="Natural language user question")


class AskResponse(BaseModel):
    """Grounded RAG answer response."""

    answer: str = Field(description="Answer text (empty string '' when grounded is False)")
    grounded: bool = Field(description="True if grounded in data; False for 'Not in the data'")
    citations: List[Citation] = Field(default_factory=list, max_length=4, description="0 to 4 citations")
    evidence: Optional[Evidence] = Field(default=None, description="Evidence object or null when not grounded")
    latency_ms: Optional[float] = Field(default=None, description="Request execution latency in milliseconds")

    @model_validator(mode="after")
    def validate_grounded_state(self) -> "AskResponse":
        if not self.grounded:
            if self.answer != "":
                # Hard requirement: answer MUST be empty string when grounded is False
                self.answer = ""
            if self.evidence is not None:
                self.evidence = None
        return self

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Investigation Models
# ---------------------------------------------------------------------------
class Fuel(BaseModel):
    """Tested fuel material metadata."""

    name: str = Field(description="Fuel material name")
    fuel_class: FuelClass = Field(description="Fuel classification (solid, gas, liquid)")
    sample_shape: str = Field(description="Geometric form factor (e.g. flat sheet, rod, burner)")
    sample_size: str = Field(description="Sample size with units (e.g. '20 mm x 100 mm x 0.3 mm')")

    model_config = ConfigDict(extra="ignore")


class Conditions(BaseModel):
    """Chamber atmospheric and ventilation boundary conditions."""

    o2_percent: Optional[RangeObj] = Field(default=None, description="Oxygen mole percent range or null")
    pressure_psi: Optional[RangeObj] = Field(default=None, description="Chamber total pressure in psi range or null")
    flow_speed_cm_s: Optional[RangeObj] = Field(default=None, description="Ventilation speed in cm/s or null")

    model_config = ConfigDict(extra="ignore")


class Investigation(BaseModel):
    """Investigation metadata matching Frontend types.ts."""

    id: str = Field(description="Unique investigation ID, e.g. inv-bass-2")
    name: str = Field(description="Investigation acronym/name, e.g. BASS-II")
    hardware: str = Field(description="Hardware platform (CIR-ACME, MSG-SPICE duct, Cygnus)")
    pillar: Pillar = Field(description="Fire safety pillar (prevention, detection, suppression, supporting)")
    objective: str = Field(description="Flight investigation objective")
    fuels: List[Fuel] = Field(default_factory=list)
    conditions: Optional[Conditions] = Field(default=None, description="Chamber atmospheric boundary conditions or null")
    variables: List[str] = Field(default_factory=list)
    sensors: List[str] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    sample: bool = Field(default=True, description="True when served from seed/stub; False for SQLite")

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# TestRecord Model
# ---------------------------------------------------------------------------
class TestRecord(BaseModel):
    """Single experimental test point matching Frontend types.ts."""

    id: str = Field(description="Unique test run ID, e.g. t-001")
    investigation_id: str = Field(description="Foreign key to Investigation.id")
    investigation_name: str = Field(description="Investigation name, e.g. BASS-II")
    fuel: str = Field(description="Specific fuel or gas tested")
    fuel_class: FuelClass = Field(description="solid, gas, or liquid")
    flow_direction: Optional[FlowDirection] = Field(default=None, description="opposed, concurrent, quiescent, or null")
    o2_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Ambient oxygen concentration % or null")
    pressure_psi: Optional[float] = Field(default=None, ge=0.0, description="Chamber pressure in psi or null")
    flow_speed_cm_s: Optional[float] = Field(default=None, description="Forced flow speed in cm/s or null")
    platform: Platform = Field(description="iss, drop_tower, or other")
    ended_early: Optional[bool] = Field(default=None, description="True if flame was still burning at end of run or null")
    result: str = Field(description="Combustion outcome description")
    spread_rate: Optional[float] = Field(default=None, description="Flame spread rate in mm/s or null")
    citation: Optional[Citation] = Field(default=None, description="Source citation or null")
    sample: bool = Field(default=True, description="True for seed/stub; False for SQLite")

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Insight Model
# ---------------------------------------------------------------------------
class Insight(BaseModel):
    """Ranked safety insight matching Frontend types.ts."""

    id: str = Field(description="Unique insight ID, e.g. ins-01")
    title: str = Field(description="Short insight title")
    summary: str = Field(description="Detailed finding summary")
    recommendation: str = Field(description="One-line operational recommendation")
    risk_level: RiskLevel = Field(description="high, medium, or low")
    safety_impact: int = Field(ge=1, le=5, description="1 to 5")
    evidence_strength: int = Field(ge=1, le=5, description="1 to 5")
    mission_relevance: int = Field(ge=1, le=5, description="1 to 5")
    score: int = Field(ge=1, le=125, description="safety_impact * evidence_strength * mission_relevance")
    score_reason: str = Field(description="Explanation of score components")
    citations: List[Citation] = Field(default_factory=list)
    reviewed: bool = Field(default=False, description="Human review status")
    sample: bool = Field(default=True, description="True for seed/stub; False for SQLite")

    @model_validator(mode="after")
    def validate_score_calculation(self) -> "Insight":
        expected = self.safety_impact * self.evidence_strength * self.mission_relevance
        if self.score != expected:
            raise ValueError(
                f"score must equal safety_impact ({self.safety_impact}) x "
                f"evidence_strength ({self.evidence_strength}) x "
                f"mission_relevance ({self.mission_relevance}) = {expected}, but got {self.score}"
            )
        return self

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Health & Secondary Models
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Healthcheck response matching the Frontend's API contract."""

    status: str = "ok"
    version: str = "v0.1-hackathon"
    sqlite_connected: bool
    ai_service_configured: bool
    disclaimer: str = "v0.1, unverified"


class SafetyMargin(BaseModel):
    """Secondary helper model: Paired 1-g vs microgravity LOI."""

    material: str
    category: str
    limit_1g_o2_percent: float
    limit_ug_o2_percent: float
    delta_o2_percent: float
    pressure_psi: float = 14.7
    flow_speed_cm_s: float
    danger_direction: str
    citation: str
    notes: str


class HabitatRelevanceItem(BaseModel):
    """Secondary helper model: Nearest test to exploration habitat."""

    test_record: TestRecord
    distance: float
    relevance_score: float
    habitat_id: str
    delta_o2_percent: float
    delta_pressure_psi: float
