"""SQLite data access layer with automatic fallback to NASA PSI seed data.

Reads from `data/flamesight.db` if present (marking records with sample=False),
or transparently falls back to the verified seed dataset (sample=True).
"""

import json
import logging
import os
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
            conn.close()
            return True
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
                results = []
                for row in rows:
                    d = dict(row)
                    d["sample"] = False
                    d["fuels"] = _parse_json_field(d.get("fuels"), default=[])
                    d["conditions"] = _parse_json_field(d.get("conditions"), default={})
                    d["variables"] = _parse_json_field(d.get("variables"), default=[])
                    d["sensors"] = _parse_json_field(d.get("sensors"), default=[])
                    d["citations"] = _parse_json_field(d.get("citations"), default=[])
                    results.append(Investigation.model_validate(d))
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
                results = []
                for row in rows:
                    d = dict(row)
                    d["sample"] = False
                    d["ended_early"] = _to_bool(d.get("ended_early"), default=False)
                    d["citation"] = _parse_json_field(d.get("citation"), default=None)
                    results.append(TestRecord.model_validate(d))
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
                results = []
                for row in rows:
                    d = dict(row)
                    d["sample"] = False
                    d["reviewed"] = _to_bool(d.get("reviewed"), default=False)
                    d["citations"] = _parse_json_field(d.get("citations"), default=[])
                    if "score" not in d or d["score"] is None:
                        impact = int(d.get("safety_impact", 4))
                        evidence = int(d.get("evidence_strength", 4))
                        relevance = int(d.get("mission_relevance", 4))
                        d["score"] = impact * evidence * relevance
                    results.append(Insight.model_validate(d))
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
