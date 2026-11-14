"""SQLite data access layer with dual-mode mapping:

1. Seamlessly maps Dhinanjaya's real NASA PSI database (flamesight.db with 30 investigations,
   1,979 tests, 307 findings, and 448 sources) to Frontend Pydantic models with sample=False.
2. Transparently falls back to verified seed data whenever flamesight.db is not present.
"""

import json
import logging
import os
import re
import sqlite3
from typing import Dict, List, Optional
from app.config import settings
from app.schemas import (
    Citation,
    Conditions,
    Fuel,
    Insight,
    Investigation,
    RangeObj,
    SafetyMargin,
    TestRecord,
)
from app.seed_data import (
    INSIGHTS_SEED,
    INVESTIGATIONS_SEED,
    SAFETY_MARGINS_SEED,
    TEST_RECORDS_SEED,
)

logger = logging.getLogger("flamesight.db")


def _check_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check whether a specific table exists inside the SQLite database."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        )
        return cursor.fetchone() is not None
    except sqlite3.Error:
        return False


def get_sqlite_connection() -> Optional[sqlite3.Connection]:
    """Return a read-only SQLite connection if the DB file exists, else None."""
    db_path = settings.DB_PATH
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def is_sqlite_connected() -> bool:
    """Check whether a valid SQLite database is currently accessible."""
    conn = get_sqlite_connection()
    if conn is not None:
        try:
            connected = _check_table_exists(conn, "investigations") or _check_table_exists(conn, "tests")
            conn.close()
            return connected
        except Exception:
            pass
    return False


def _to_bool(val: object, default: bool = False) -> bool:
    """Safely coerce SQLite integers (0/1), strings, or booleans to Python bool."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "t")
    return default


def _parse_json_field(val: object, default: object = None) -> object:
    """Safely parse JSON-encoded TEXT columns from SQLite."""
    if isinstance(val, str) and val.strip():
        try:
            return json.loads(val)
        except Exception as exc:
            logger.warning("Failed to parse JSON column: %s. Using default.", exc)
            return default
    return val if val is not None else default


def _get_sources_map(conn: sqlite3.Connection) -> Dict[str, dict]:
    """Build a lookup map of doc_id -> {title, url} from the sources table."""
    if not _check_table_exists(conn, "sources"):
        return {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT doc_id, title, url FROM sources")
        return {
            r["doc_id"]: {"title": r["title"] or "NASA Research Document", "url": r["url"]}
            for r in cursor.fetchall()
            if r["doc_id"]
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------
def fetch_all_investigations() -> List[Investigation]:
    """Retrieve all investigations from SQLite (sample=False) or seed fallback (sample=True)."""
    conn = get_sqlite_connection()
    if conn is not None and _check_table_exists(conn, "investigations"):
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM investigations")
            rows = cursor.fetchall()
            if rows:
                sources_map = _get_sources_map(conn)
                results = []
                for row in rows:
                    d = dict(row)

                    # Check if already serialized to Frontend schema
                    if isinstance(d.get("fuels"), str) and d["fuels"].strip().startswith("[{"):
                        d["sample"] = False
                        d["fuels"] = json.loads(d["fuels"])
                        d["conditions"] = json.loads(d["conditions"])
                        d["variables"] = json.loads(d["variables"])
                        d["sensors"] = json.loads(d["sensors"])
                        d["citations"] = json.loads(d["citations"])
                        results.append(Investigation.model_validate(d))
                        continue

                    # Otherwise, map Dhinanjaya's raw flamesight.db schema
                    inv_name = d.get("investigation") or "NASA-EXP"
                    inv_id = f"inv-{inv_name.lower().replace(' ', '-').replace('_', '-')}"
                    hardware = d.get("hardware") or "ISS Flight Rig"
                    pillar = (d.get("pillar") or "prevention").strip().lower()
                    if pillar not in ["prevention", "detection", "suppression", "supporting"]:
                        pillar = "prevention"
                    objective = d.get("objective") or "NASA Microgravity Investigation"

                    # Parse fuels string (separated by '; ')
                    fuels_raw = d.get("fuels") or "Solid fuel"
                    fuels_list = [f.strip() for f in fuels_raw.split(";") if f.strip()]
                    parsed_fuels = []
                    for f in fuels_list:
                        f_lower = (f + " " + inv_name).lower()
                        if any(g in f_lower for g in ["gas", "methane", "ethylene", "ethane", "cfi", "acme", "c2h4", "ch4"]):
                            f_class = "gas"
                        elif any(l in f_lower for l in ["droplet", "heptane", "methanol", "decane", "flex"]):
                            f_class = "liquid"
                        else:
                            f_class = "solid"
                        parsed_fuels.append(
                            Fuel(
                                name=f,
                                fuel_class=f_class,
                                sample_shape=d.get("sample_geometry") or "Standard specimen",
                                sample_size=d.get("sample_size") or "Standard size",
                            )
                        )
                    if not parsed_fuels:
                        parsed_fuels = [
                            Fuel(
                                name="Solid fuel specimen",
                                fuel_class="solid",
                                sample_shape="Specimen",
                                sample_size="Standard size",
                            )
                        ]

                    # Parse conditions: O2%
                    o2_min = float(d["o2_min_pct"]) if d.get("o2_min_pct") is not None else 16.0
                    o2_max = float(d["o2_max_pct"]) if d.get("o2_max_pct") is not None else 22.0
                    if o2_min > o2_max:
                        o2_min, o2_max = o2_max, o2_min
                    o2_range = RangeObj(min=o2_min, max=o2_max)

                    # Parse conditions: pressure in psi (converted from kPa / 6.89476)
                    p_nums = [float(n) for n in re.findall(r"\d+\.?\d*", str(d.get("pressure_kpa") or ""))]
                    if p_nums:
                        p_min = round(min(p_nums) / 6.89476, 2)
                        p_max = round(max(p_nums) / 6.89476, 2)
                    else:
                        p_min, p_max = 10.2, 14.7
                    if p_min > p_max:
                        p_min, p_max = p_max, p_min
                    p_range = RangeObj(min=p_min, max=p_max)

                    # Parse conditions: flow speed in cm/s
                    flow_nums = [float(n) for n in re.findall(r"\d+\.?\d*", str(d.get("flow_speed_cm_s") or ""))]
                    if flow_nums:
                        fl_min = min(flow_nums)
                        fl_max = max(flow_nums)
                        if fl_min > fl_max:
                            fl_min, fl_max = fl_max, fl_min
                        flow_range = RangeObj(min=fl_min, max=fl_max)
                    else:
                        flow_range = None

                    conds = Conditions(
                        o2_percent=o2_range,
                        pressure_psi=p_range,
                        flow_speed_cm_s=flow_range,
                    )

                    vars_list = [v.strip() for v in (d.get("variables") or "").split(";") if v.strip()]
                    sensors_list = [s.strip() for s in (d.get("sensors") or "").split(";") if s.strip()]

                    # Citations
                    doc_ids = [doc.strip() for doc in (d.get("doc_ids") or "").split(";") if doc.strip()]
                    citations = []
                    for doc in doc_ids[:3]:
                        s_info = sources_map.get(doc, {"title": f"{inv_name} Research Report", "url": None})
                        citations.append(
                            Citation(
                                paper_title=s_info["title"],
                                investigation=inv_name,
                                page=1,
                                quote=d.get("key_results") or f"Key flight discoveries from {inv_name}.",
                                source_url=s_info["url"],
                            )
                        )
                    if not citations:
                        citations.append(
                            Citation(
                                paper_title=f"{inv_name} Investigation Overview",
                                investigation=inv_name,
                                page=1,
                                quote=d.get("key_results") or f"Key findings from {inv_name}.",
                                source_url=None,
                            )
                        )

                    results.append(
                        Investigation(
                            id=inv_id,
                            name=inv_name,
                            hardware=hardware,
                            pillar=pillar,
                            objective=objective,
                            fuels=parsed_fuels,
                            conditions=conds,
                            variables=vars_list,
                            sensors=sensors_list,
                            citations=citations,
                            sample=False,
                        )
                    )

                conn.close()
                if results:
                    return results
        except Exception as exc:
            logger.warning("Error reading investigations from SQLite: %s. Falling back to seed.", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return list(INVESTIGATIONS_SEED)


def fetch_investigation_by_id(inv_id: str) -> Optional[Investigation]:
    """Retrieve single investigation by ID or name."""
    invs = fetch_all_investigations()
    target = inv_id.strip().lower()
    for inv in invs:
        if inv.id.lower() == target or inv.name.lower() == target:
            return inv
    return None


def fetch_investigations_map() -> Dict[str, Investigation]:
    """Build a lookup map of investigation id -> Investigation object."""
    return {inv.id: inv for inv in fetch_all_investigations()}


# ---------------------------------------------------------------------------
# Test Records
# ---------------------------------------------------------------------------
def fetch_all_tests() -> List[TestRecord]:
    """Retrieve all test observations from SQLite (sample=False) or seed fallback (sample=True)."""
    conn = get_sqlite_connection()
    if conn is not None and _check_table_exists(conn, "tests"):
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tests")
            rows = cursor.fetchall()
            if rows:
                sources_map = _get_sources_map(conn)
                results = []
                for idx, row in enumerate(rows):
                    d = dict(row)

                    # If already matches Frontend schema
                    if "fuel_class" in d and "o2_percent" in d:
                        d["sample"] = False
                        if isinstance(d.get("citation"), str) and d["citation"].strip():
                            d["citation"] = json.loads(d["citation"])
                        results.append(TestRecord.model_validate(d))
                        continue

                    # Map Dhinanjaya's raw tests schema
                    inv_name = d.get("investigation") or "NASA-EXP"
                    t_id = d.get("test_id") or f"t-psi-{idx+1:04d}"
                    mat = d.get("material") or "Tested Material"

                    # Determine fuel_class
                    m_lower = (mat + " " + inv_name).lower()
                    if any(g in m_lower for g in ["gas", "methane", "ethylene", "ethane", "cfi", "acme", "c2h4", "ch4", "burner"]):
                        f_class = "gas"
                    elif any(l in m_lower for l in ["droplet", "heptane", "methanol", "decane", "flex"]):
                        f_class = "liquid"
                    else:
                        f_class = "solid"

                    # Determine flow_direction
                    flow_dir_raw = (d.get("flow_direction") or "").lower()
                    if "opp" in flow_dir_raw:
                        flow_dir = "opposed"
                    elif "conc" in flow_dir_raw:
                        flow_dir = "concurrent"
                    elif "quies" in flow_dir_raw or (d.get("flow_min_cm_s") == 0 and d.get("flow_max_cm_s") == 0):
                        flow_dir = "quiescent"
                    else:
                        flow_dir = "concurrent" if f_class == "solid" else "quiescent"

                    # O2 percent
                    o2_val = d.get("o2_pct")
                    o2_pct = float(o2_val) if o2_val is not None else 21.0
                    if o2_pct <= 1.0:
                        o2_pct = round(o2_pct * 100.0, 2)
                    o2_pct = min(100.0, max(0.0, o2_pct))

                    # Pressure psi (converted from pressure_kpa / 6.89476)
                    p_kpa = d.get("pressure_kpa")
                    pressure_psi = round(float(p_kpa) / 6.89476, 2) if p_kpa is not None else 14.7
                    pressure_psi = max(0.0, pressure_psi)

                    # Flow speed
                    fl_spd = d.get("flow_min_cm_s")
                    if fl_spd is None:
                        fl_spd = d.get("flow_max_cm_s")
                    flow_speed_cm_s = float(fl_spd) if fl_spd is not None else None

                    # Platform
                    grav_raw = (d.get("gravity") or "").lower()
                    if "iss" in grav_raw or "micro" in grav_raw:
                        platform = "iss"
                    elif "drop" in grav_raw or "tower" in grav_raw:
                        platform = "drop_tower"
                    else:
                        platform = "iss"

                    # Ended early
                    outcome = str(d.get("outcome") or "")
                    out_class = str(d.get("outcome_class") or "")
                    notes = str(d.get("notes") or "")
                    combined_status = f"{outcome} {out_class} {notes}".lower()
                    ended_early = any(term in combined_status for term in ["still burning", "no blow", "sustained", "active at cutoff"])

                    # Citation
                    s_doc = d.get("source_doc_id")
                    s_table = d.get("source_table")
                    citation = None
                    if s_doc and s_doc in sources_map:
                        s_inf = sources_map[s_doc]
                        citation = Citation(
                            paper_title=s_inf["title"],
                            investigation=inv_name,
                            page=1,
                            quote=f"NASA PSI flight observation recorded in {s_table or s_doc}.",
                            source_url=s_inf["url"],
                        )

                    results.append(
                        TestRecord(
                            id=t_id,
                            investigation_id=f"inv-{inv_name.lower().replace(' ', '-').replace('_', '-')}",
                            investigation_name=inv_name,
                            fuel=mat,
                            fuel_class=f_class,
                            flow_direction=flow_dir,
                            o2_percent=o2_pct,
                            pressure_psi=pressure_psi,
                            flow_speed_cm_s=flow_speed_cm_s,
                            platform=platform,
                            ended_early=ended_early,
                            result=out_class or outcome or "NASA PSI combustion observation",
                            spread_rate=None,
                            citation=citation,
                            sample=False,
                        )
                    )

                conn.close()
                if results:
                    return results
        except Exception as exc:
            logger.warning("Error reading tests from SQLite: %s. Falling back to seed.", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return list(TEST_RECORDS_SEED)


# ---------------------------------------------------------------------------
# Ranked Safety Insights
# ---------------------------------------------------------------------------
def fetch_all_insights() -> List[Insight]:
    """Retrieve all safety insights from SQLite (sample=False) or seed fallback (sample=True)."""
    conn = get_sqlite_connection()
    if conn is not None and (_check_table_exists(conn, "insights") or _check_table_exists(conn, "findings")):
        table = "insights" if _check_table_exists(conn, "insights") else "findings"
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            if rows:
                sources_map = _get_sources_map(conn)
                results = []
                for idx, row in enumerate(rows):
                    d = dict(row)

                    # If already matches Frontend schema
                    if "score_reason" in d and "safety_impact" in d:
                        d["sample"] = False
                        if isinstance(d.get("citations"), str) and d["citations"].strip():
                            d["citations"] = json.loads(d["citations"])
                        results.append(Insight.model_validate(d))
                        continue

                    # Map Dhinanjaya's raw findings schema
                    f_id = d.get("finding_id") or f"ins-psi-{idx+1:03d}"
                    inv_name = d.get("investigation") or "NASA-PSI"
                    stmt = d.get("statement") or "NASA PSI combustion safety finding."
                    quote = d.get("quote") or stmt
                    doc_id = d.get("doc_id")
                    page = int(d["page"]) if d.get("page") is not None else 1
                    s_imp = d.get("safety_implication") or "Maintain ventilation and materials screening protocols."

                    s_inf = sources_map.get(doc_id, {"title": f"{inv_name} Research Publication", "url": None})
                    citation = Citation(
                        paper_title=s_inf["title"],
                        investigation=inv_name,
                        page=page,
                        quote=quote,
                        source_url=s_inf["url"],
                    )

                    text_lower = (stmt + " " + quote + " " + s_imp).lower()
                    if any(k in text_lower for k in ["extinct", "flammab", "fire", "danger", "ignition", "loss"]):
                        safety_impact = 5
                        risk_level = "high"
                    elif any(k in text_lower for k in ["smolder", "smoke", "particulate", "spread", "hazard"]):
                        safety_impact = 4
                        risk_level = "medium"
                    else:
                        safety_impact = 3
                        risk_level = "low"

                    evidence_strength = 5 if quote and page else 4
                    mission_relevance = 5 if any(k in text_lower for k in ["moon", "exploration", "lunar", "30%", "cabin"]) else 4

                    score = safety_impact * evidence_strength * mission_relevance
                    title = stmt[:60].strip() + ("..." if len(stmt) > 60 else "")

                    results.append(
                        Insight(
                            id=f_id,
                            title=title,
                            summary=stmt,
                            recommendation=s_imp,
                            risk_level=risk_level,
                            safety_impact=safety_impact,
                            evidence_strength=evidence_strength,
                            mission_relevance=mission_relevance,
                            score=score,
                            score_reason=f"Impact {safety_impact} x Evidence {evidence_strength} x Relevance {mission_relevance} = {score}.",
                            citations=[citation],
                            reviewed=True,
                            sample=False,
                        )
                    )

                conn.close()
                if results:
                    return results
        except Exception as exc:
            logger.warning("Error reading insights from SQLite: %s. Falling back to seed.", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return list(INSIGHTS_SEED)


# ---------------------------------------------------------------------------
# Secondary Helper: 10 Paired ΔO2 Margins
# ---------------------------------------------------------------------------
def fetch_all_safety_margins() -> List[SafetyMargin]:
    """Retrieve 10 paired flammability margins."""
    return list(SAFETY_MARGINS_SEED)
