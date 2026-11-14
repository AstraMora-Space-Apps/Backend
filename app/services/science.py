"""Scientific computation and filtering logic conforming to Frontend data contract."""

import math
from typing import Dict, List, Optional
from app.schemas import (
    HabitatRelevanceItem,
    Insight,
    Investigation,
    SafetyMargin,
    TestRecord,
)


def overlaps(
    lo: Optional[float],
    hi: Optional[float],
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> bool:
    """Range overlap helper: returns True if [lo, hi] overlaps [min_val, max_val].

    If no boundary filter is given (min_val and max_val are None), returns True.
    If a filter is applied but lo or hi is None, returns False (unknown range cannot match).
    """
    if min_val is None and max_val is None:
        return True
    if lo is None or hi is None:
        return False
    return (min_val is None or hi >= min_val) and (max_val is None or lo <= max_val)


def within(
    val: Optional[float],
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> bool:
    """Inclusive range helper: returns True if val is within [min_val, max_val].

    If no boundary filter is given (min_val and max_val are None), returns True.
    If a filter is applied but val is None, returns False (unknown value cannot match).
    """
    if min_val is None and max_val is None:
        return True
    if val is None:
        return False
    return (min_val is None or val >= min_val) and (max_val is None or val <= max_val)


def same_text(a: Optional[str], b: Optional[str]) -> bool:
    """Case-insensitive exact string match."""
    if not b:
        return True
    if a is None:
        return False
    return a.strip().lower() == b.strip().lower()


def includes_text(haystack: List[Optional[str]], q: Optional[str]) -> bool:
    """Case-insensitive substring search across string list."""
    if not q or not q.strip():
        return True
    needle = q.strip().lower()
    return any(needle in h.lower() for h in haystack if h)


class ScienceService:
    """Handles exact filtering semantics, habitat distance ranking, and guardrails."""

    @staticmethod
    def match_investigation(
        inv: Investigation,
        fuel_class: Optional[str] = None,
        hardware: Optional[str] = None,
        pillar: Optional[str] = None,
        o2_min: Optional[float] = None,
        o2_max: Optional[float] = None,
        pressure_min: Optional[float] = None,
        pressure_max: Optional[float] = None,
        q: Optional[str] = None,
    ) -> bool:
        """Filter an investigation against criteria. Range filters use OVERLAP."""
        cond = inv.conditions
        cond_o2 = cond.o2_percent if cond else None
        cond_p = cond.pressure_psi if cond else None

        if fuel_class and not any(fuel.fuel_class == fuel_class for fuel in inv.fuels):
            return False

        if hardware and not same_text(inv.hardware, hardware):
            return False

        if pillar and inv.pillar != pillar:
            return False

        o2_lo = cond_o2.min if cond_o2 else None
        o2_hi = cond_o2.max if cond_o2 else None
        if not overlaps(o2_lo, o2_hi, o2_min, o2_max):
            return False

        p_lo = cond_p.min if cond_p else None
        p_hi = cond_p.max if cond_p else None
        if not overlaps(p_lo, p_hi, pressure_min, pressure_max):
            return False

        if q:
            haystack = [inv.name, inv.objective, inv.hardware] + [f.name for f in inv.fuels]
            if not includes_text(haystack, q):
                return False

        return True

    @staticmethod
    def match_test(
        test: TestRecord,
        investigations_by_id: Dict[str, Investigation],
        investigation_id: Optional[str] = None,
        fuel_class: Optional[str] = None,
        hardware: Optional[str] = None,
        pillar: Optional[str] = None,
        o2_min: Optional[float] = None,
        o2_max: Optional[float] = None,
        pressure_min: Optional[float] = None,
        pressure_max: Optional[float] = None,
        q: Optional[str] = None,
    ) -> bool:
        """Filter an experimental test against criteria. Range filters use INCLUSIVE WITHIN."""
        inv = investigations_by_id.get(test.investigation_id)

        if investigation_id and test.investigation_id != investigation_id:
            return False

        if fuel_class and test.fuel_class != fuel_class:
            return False

        if hardware and (inv is None or not same_text(inv.hardware, hardware)):
            return False

        if pillar and (inv is None or inv.pillar != pillar):
            return False

        if not within(test.o2_percent, o2_min, o2_max):
            return False

        if not within(test.pressure_psi, pressure_min, pressure_max):
            return False

        if q:
            haystack = [test.investigation_name, test.fuel, test.result]
            if not includes_text(haystack, q):
                return False

        return True

    @staticmethod
    def rank_insights(insights: List[Insight]) -> List[Insight]:
        """Return insights sorted descending strictly by score."""
        return sorted(insights, key=lambda x: x.score, reverse=True)

    @staticmethod
    def rank_tests_for_habitat(
        tests: List[TestRecord],
        target_o2_percent: float,
        target_pressure_psi: float,
        limit: int = 10,
    ) -> List[HabitatRelevanceItem]:
        """Rank tests by normalized Euclidean distance to a target habitat atmosphere.

        Skips tests whose o2_percent or pressure_psi is null.
        """
        items: List[HabitatRelevanceItem] = []
        for t in tests:
            if t.o2_percent is None or t.pressure_psi is None:
                continue

            d_o2 = round(t.o2_percent - target_o2_percent, 2)
            d_p = round(t.pressure_psi - target_pressure_psi, 2)
            # Normalization scale (O2 ~100%, Pressure ~16 psi, matching Frontend relevance.ts)
            norm_o2 = d_o2 / 100.0
            norm_p = d_p / 16.0
            dist = math.sqrt(norm_o2**2 + norm_p**2)
            score = round(1.0 / (1.0 + 5.0 * dist), 4)

            items.append(
                HabitatRelevanceItem(
                    test_record=t,
                    distance=round(dist, 4),
                    relevance_score=score,
                    habitat_id="target",
                    delta_o2_percent=d_o2,
                    delta_pressure_psi=d_p,
                )
            )

        items.sort(key=lambda x: x.relevance_score, reverse=True)
        return items[:limit]


science_service = ScienceService()
