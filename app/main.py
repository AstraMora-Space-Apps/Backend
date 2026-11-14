"""FlameSight FastAPI Backend-for-Frontend (BFF) Gateway.

Strictly implements Frontend types.ts, api.ts, and API_ASSUMPTIONS.md contracts.
"""

from contextlib import asynccontextmanager
import csv
import io
import time
from typing import AsyncGenerator, List, Optional
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from app.config import settings
from app.db import (
    fetch_all_insights,
    fetch_all_investigations,
    fetch_all_safety_margins,
    fetch_all_tests,
    fetch_investigations_map,
    is_sqlite_connected,
)
from app.schemas import (
    AskRequest,
    AskResponse,
    FuelClass,
    HabitatRelevanceItem,
    HealthResponse,
    Insight,
    Investigation,
    Pillar,
    SafetyMargin,
    TestRecord,
)
from app.services.ai_proxy import ai_proxy_service
from app.services.science import science_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan managing async client pooling."""
    ai_proxy_service.init_client()
    print(f"[{settings.APP_NAME}] Started. SQLite connected: {is_sqlite_connected()}")
    yield
    await ai_proxy_service.close_client()
    print(f"[{settings.APP_NAME}] Shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="FlameSight BFF API Gateway matching Frontend contract 100%.",
    lifespan=lifespan,
)

# Configure CORS: Allow all origins and explicitly permit Vercel domains and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global Exception Handlers
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": str(exc),
            "version": settings.APP_VERSION,
            "disclaimer": settings.DISCLAIMER,
        },
    )


# ---------------------------------------------------------------------------
# Health & Root Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Healthcheck endpoint matching Dinith's contract",
)
async def health() -> HealthResponse:
    """Check backend health and SQLite connection status."""
    sqlite_ok = is_sqlite_connected()
    ai_configured = bool(settings.AI_SERVICE_URL and settings.AI_SERVICE_URL.strip())
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        sqlite_connected=sqlite_ok,
        ai_service_configured=ai_configured,
        disclaimer=settings.DISCLAIMER,
    )


@app.get("/", tags=["System"], summary="Root endpoint")
async def root() -> dict:
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "disclaimer": settings.DISCLAIMER,
        "health": "/health",
        "docs": "/docs",
    }


# ---------------------------------------------------------------------------
# AI Q&A Endpoint (POST /ask)
# ---------------------------------------------------------------------------
@app.post(
    "/ask",
    response_model=AskResponse,
    tags=["AI & RAG"],
    summary="Ask FlameSight RAG Q&A",
)
async def ask_endpoint(request: AskRequest) -> AskResponse:
    """Asynchronously route question with <8.5s timeout and grounded fallback."""
    return await ai_proxy_service.ask(request)


@app.post(
    "/cache/clear",
    tags=["AI & RAG"],
    summary="Clear the in-memory /ask TTL cache",
)
async def clear_cache_endpoint() -> dict:
    """Clear cached Q&A responses."""
    count = ai_proxy_service.clear_cache()
    return {"status": "ok", "cleared": True, "entries_cleared": count}


# ---------------------------------------------------------------------------
# Investigations Endpoint (GET /investigations)
# ---------------------------------------------------------------------------
@app.get(
    "/investigations",
    response_model=List[Investigation],
    tags=["Investigations"],
    summary="List investigations with overlap range filters",
)
async def get_investigations_endpoint(
    fuel_class: Optional[FuelClass] = Query(None, description="solid, gas, or liquid"),
    hardware: Optional[str] = Query(None, description="Exact hardware name, case-insensitive"),
    pillar: Optional[Pillar] = Query(None, description="prevention, detection, suppression, supporting"),
    o2_min: Optional[float] = Query(None, description="Oxygen % min"),
    o2_max: Optional[float] = Query(None, description="Oxygen % max"),
    pressure_min: Optional[float] = Query(None, description="Pressure psi min"),
    pressure_max: Optional[float] = Query(None, description="Pressure psi max"),
    q: Optional[str] = Query(None, description="Free-text search"),
) -> List[Investigation]:
    """Returns raw JSON array of Investigation matching criteria (ranges overlap)."""
    all_invs = fetch_all_investigations()
    return [
        inv
        for inv in all_invs
        if science_service.match_investigation(
            inv=inv,
            fuel_class=fuel_class,
            hardware=hardware,
            pillar=pillar,
            o2_min=o2_min,
            o2_max=o2_max,
            pressure_min=pressure_min,
            pressure_max=pressure_max,
            q=q,
        )
    ]


# ---------------------------------------------------------------------------
# Tests Endpoint (GET /tests)
# ---------------------------------------------------------------------------
@app.get(
    "/tests",
    response_model=List[TestRecord],
    tags=["Tests"],
    summary="List experimental test records with inclusive within filters",
)
async def get_tests_endpoint(
    investigation_id: Optional[str] = Query(None, description="Filter by investigation ID"),
    fuel_class: Optional[FuelClass] = Query(None, description="solid, gas, or liquid"),
    hardware: Optional[str] = Query(None, description="Exact hardware name, case-insensitive"),
    pillar: Optional[Pillar] = Query(None, description="prevention, detection, suppression, supporting"),
    o2_min: Optional[float] = Query(None, description="Oxygen % min"),
    o2_max: Optional[float] = Query(None, description="Oxygen % max"),
    pressure_min: Optional[float] = Query(None, description="Pressure psi min"),
    pressure_max: Optional[float] = Query(None, description="Pressure psi max"),
    q: Optional[str] = Query(None, description="Free-text search"),
) -> List[TestRecord]:
    """Returns raw JSON array of TestRecord matching criteria (ranges within inclusive)."""
    all_tests = fetch_all_tests()
    invs_by_id = fetch_investigations_map()

    return [
        t
        for t in all_tests
        if science_service.match_test(
            test=t,
            investigations_by_id=invs_by_id,
            investigation_id=investigation_id,
            fuel_class=fuel_class,
            hardware=hardware,
            pillar=pillar,
            o2_min=o2_min,
            o2_max=o2_max,
            pressure_min=pressure_min,
            pressure_max=pressure_max,
            q=q,
        )
    ]


# ---------------------------------------------------------------------------
# Insights Endpoint (GET /insights)
# ---------------------------------------------------------------------------
@app.get(
    "/insights",
    response_model=List[Insight],
    tags=["Insights"],
    summary="List ranked insights sorted descending by score",
)
async def get_insights_endpoint() -> List[Insight]:
    """Returns raw JSON array of Insight sorted strictly descending by score."""
    insights = fetch_all_insights()
    return science_service.rank_insights(insights)


# ---------------------------------------------------------------------------
# CSV Export Endpoint (GET /export/csv)
# ---------------------------------------------------------------------------
@app.get(
    "/export/csv",
    tags=["Export"],
    summary="Export filtered per-test dataset as CSV",
)
async def export_csv_endpoint(
    investigation_id: Optional[str] = Query(None),
    fuel_class: Optional[FuelClass] = Query(None),
    hardware: Optional[str] = Query(None),
    pillar: Optional[Pillar] = Query(None),
    o2_min: Optional[float] = Query(None),
    o2_max: Optional[float] = Query(None),
    pressure_min: Optional[float] = Query(None),
    pressure_max: Optional[float] = Query(None),
    q: Optional[str] = Query(None),
) -> Response:
    """Streams CSV file matching the exact filter params as /tests."""
    all_tests = fetch_all_tests()
    invs_by_id = fetch_investigations_map()

    matching_tests = [
        t
        for t in all_tests
        if science_service.match_test(
            test=t,
            investigations_by_id=invs_by_id,
            investigation_id=investigation_id,
            fuel_class=fuel_class,
            hardware=hardware,
            pillar=pillar,
            o2_min=o2_min,
            o2_max=o2_max,
            pressure_min=pressure_min,
            pressure_max=pressure_max,
            q=q,
        )
    ]

    output = io.StringIO()
    # Required Hackathon Header
    output.write("# FlameSight Per-Test Dataset (v0.1, unverified extraction - NASA Space Apps 2026)\n")

    writer = csv.writer(output)
    writer.writerow([
        "test_id",
        "investigation_id",
        "investigation",
        "fuel",
        "fuel_class",
        "flow_direction",
        "o2_percent",
        "pressure_psi",
        "flow_speed_cm_s",
        "platform",
        "ended_early",
        "result",
        "spread_rate",
        "citation_paper",
        "citation_page",
        "sample",
        "dataset_status",
    ])

    for t in matching_tests:
        writer.writerow([
            t.id,
            t.investigation_id,
            t.investigation_name,
            t.fuel,
            t.fuel_class,
            t.flow_direction,
            t.o2_percent,
            t.pressure_psi,
            t.flow_speed_cm_s if t.flow_speed_cm_s is not None else "",
            t.platform,
            t.ended_early,
            t.result,
            t.spread_rate if t.spread_rate is not None else "",
            t.citation.paper_title if t.citation else "",
            t.citation.page if t.citation and t.citation.page is not None else "",
            t.sample,
            "v0.1, preliminary / unverified",
        ])

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=flamesight_per_test_v0.1_unverified.csv",
            "Cache-Control": "no-cache",
        },
    )


# ---------------------------------------------------------------------------
# Secondary API Aliases (for backward compatibility & tools)
# ---------------------------------------------------------------------------
@app.get("/api/investigations", response_model=List[Investigation], include_in_schema=False)
async def alias_investigations(
    fuel_class: Optional[FuelClass] = None,
    hardware: Optional[str] = None,
    pillar: Optional[Pillar] = None,
    o2_min: Optional[float] = None,
    o2_max: Optional[float] = None,
    pressure_min: Optional[float] = None,
    pressure_max: Optional[float] = None,
    q: Optional[str] = None,
) -> List[Investigation]:
    return await get_investigations_endpoint(
        fuel_class=fuel_class,
        hardware=hardware,
        pillar=pillar,
        o2_min=o2_min,
        o2_max=o2_max,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        q=q,
    )


@app.get("/api/tests", response_model=List[TestRecord], include_in_schema=False)
async def alias_tests(
    investigation_id: Optional[str] = None,
    fuel_class: Optional[FuelClass] = None,
    hardware: Optional[str] = None,
    pillar: Optional[Pillar] = None,
    o2_min: Optional[float] = None,
    o2_max: Optional[float] = None,
    pressure_min: Optional[float] = None,
    pressure_max: Optional[float] = None,
    q: Optional[str] = None,
) -> List[TestRecord]:
    return await get_tests_endpoint(
        investigation_id=investigation_id,
        fuel_class=fuel_class,
        hardware=hardware,
        pillar=pillar,
        o2_min=o2_min,
        o2_max=o2_max,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        q=q,
    )


@app.get("/api/insights", response_model=List[Insight], include_in_schema=False)
async def alias_insights() -> List[Insight]:
    return await get_insights_endpoint()


@app.get("/api/tests/export-csv", include_in_schema=False)
async def alias_export_csv(
    investigation_id: Optional[str] = None,
    fuel_class: Optional[FuelClass] = None,
    hardware: Optional[str] = None,
    pillar: Optional[Pillar] = None,
    o2_min: Optional[float] = None,
    o2_max: Optional[float] = None,
    pressure_min: Optional[float] = None,
    pressure_max: Optional[float] = None,
    q: Optional[str] = None,
) -> Response:
    return await export_csv_endpoint(
        investigation_id=investigation_id,
        fuel_class=fuel_class,
        hardware=hardware,
        pillar=pillar,
        o2_min=o2_min,
        o2_max=o2_max,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        q=q,
    )


@app.get("/api/safety-margins", response_model=List[SafetyMargin], tags=["Secondary Tools"])
async def get_safety_margins() -> List[SafetyMargin]:
    return fetch_all_safety_margins()


@app.get("/api/coverage/habitat-finder", response_model=List[HabitatRelevanceItem], tags=["Secondary Tools"])
async def habitat_finder(
    o2_percent: float = Query(30.0, description="Target O2 %"),
    pressure_psi: float = Query(10.2, description="Target pressure psi"),
    limit: int = Query(10, ge=1, le=50),
) -> List[HabitatRelevanceItem]:
    all_tests = fetch_all_tests()
    return science_service.rank_tests_for_habitat(
        tests=all_tests,
        target_o2_percent=o2_percent,
        target_pressure_psi=pressure_psi,
        limit=limit,
    )
