"""SQLite data access layer with automatic fallback to NASA PSI seed data.

Reads from `data/flamesight.db` if present (marking records with sample=False),
or transparently falls back to the verified seed dataset (sample=True).
"""

import json
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
            results = []
            for row in rows:
                d = dict(row)
                d["sample"] = False
                # Parse JSON fields if stored as text in SQLite
                if isinstance(d.get("fuels"), str):
                    d["fuels"] = json.loads(d["fuels"])
                if isinstance(d.get("conditions"), str):
                    d["conditions"] = json.loads(d["conditions"])
                if isinstance(d.get("variables"), str):
                    d["variables"] = json.loads(d["variables"])
                if isinstance(d.get("sensors"), str):
                    d["sensors"] = json.loads(d["sensors"])
                if isinstance(d.get("citations"), str):
                    d["citations"] = json.loads(d["citations"])
                results.append(Investigation.model_validate(d))
            conn.close()
            if results:
                return results
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
            results = []
            for row in rows:
                d = dict(row)
                d["sample"] = False
                if isinstance(d.get("citation"), str) and d["citation"].strip():
                    d["citation"] = json.loads(d["citation"])
                results.append(TestRecord.model_validate(d))
            conn.close()
            if results:
                return results
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
            results = []
            for row in rows:
                d = dict(row)
                d["sample"] = False
                if isinstance(d.get("citations"), str) and d["citations"].strip():
                    d["citations"] = json.loads(d["citations"])
                # Compute score if missing
                if "score" not in d:
                    d["score"] = d["safety_impact"] * d["evidence_strength"] * d["mission_relevance"]
                results.append(Insight.model_validate(d))
            conn.close()
            if results:
                return results
        except Exception:
            pass

    return list(INSIGHTS_SEED)


# ---------------------------------------------------------------------------
# Secondary Helper: 10 Paired ΔO2 Margins
# ---------------------------------------------------------------------------
def fetch_all_safety_margins() -> List[SafetyMargin]:
    """Retrieve 10 paired flammability margins."""
    return list(SAFETY_MARGINS_SEED)
