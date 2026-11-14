# FlameSight Backend — BFF API Gateway

> **Team AstraMora — NASA Space Apps Challenge 2026**  
> *Challenge:* Flame in Freefall (Virtual Track)  
> *Release:* `v0.1-hackathon` (disclaimer: `v0.1, unverified`)

FlameSight Backend is the production-ready **Backend-for-Frontend (BFF) API Gateway** built with **FastAPI**. It powers the FlameSight dashboard by serving structured microgravity combustion research from the **NASA Physical Sciences Informatics (PSI)** repository, computing exploration habitat relevance metrics, and proxying natural language queries to the AI RAG microservice with automatic failover, <8.5s latency enforcement, and in-memory TTL caching.

---

## 100% Contract Conformance with Frontend

This service strictly satisfies every schema, enum, query parameter, unit, and response shape defined by Dinith in:
- `Frontend/src/lib/types.ts`
- `Frontend/src/lib/api.ts`
- `Frontend/docs/API_ASSUMPTIONS.md`
- `Frontend/src/app/dev/contract/ContractChecks.tsx`

---

## REST Endpoints Catalog

| Method | Endpoint | Query / Body | Response Shape | Description |
|---|---|---|---|---|
| `GET` | `/health` | None | `HealthResponse` | `{ status: "ok", version: "v0.1-hackathon", sqlite_connected: bool, ai_service_configured: bool, disclaimer: "v0.1, unverified" }` |
| `POST` | `/ask` | `{ "question": str }` | `AskResponse` | Natural language Q&A. When `grounded` is `False`, `answer` is strictly `""`, `citations: []`, `evidence: None`. |
| `POST` | `/cache/clear` | None | `{ status: "ok", cleared: true }` | Clears in-memory Q&A TTL cache. |
| `GET` | `/investigations` | `fuel_class`, `hardware`, `pillar`, `o2_min`, `o2_max`, `pressure_min`, `pressure_max`, `q` | `Investigation[]` (raw array) | Range filters check **overlap** (`cond.max >= filter_min && cond.min <= filter_max`). |
| `GET` | `/tests` | `investigation_id`, `fuel_class`, `hardware`, `pillar`, `o2_min`, `o2_max`, `pressure_min`, `pressure_max`, `q` | `TestRecord[]` (raw array) | Range filters check **inclusive within** (`filter_min <= val <= filter_max`). |
| `GET` | `/insights` | None | `Insight[]` (raw array) | Sorted descending by `score = safety_impact * evidence_strength * mission_relevance` (1 to 125). |
| `GET` | `/export/csv` | Same filters as `/tests` | `text/csv` stream | Streams `flamesight_per_test_v0.1_unverified.csv` with `# FlameSight Per-Test Dataset (v0.1, unverified extraction - NASA Space Apps 2026)` header. |

*(Secondary endpoints `/api/safety-margins` and `/api/coverage/habitat-finder` are also exposed for exploration habitat tools)*

---

## Units and Enums Convention

- **Pressure:** Total chamber pressure is in **psi** (e.g. `14.7` Earth/ISS, `10.2` Moon Base, `4.3` Spacesuit).
- **Oxygen:** Volume/mole percentage in `%` (e.g. `21.0` Earth, `30.0` Moon Base).
- **Flame Spread Rate:** Flame velocity is in **mm/s**.
- **Fuel Class:** `solid`, `gas`, `liquid`.
- **Flow Direction:** `opposed`, `concurrent`, `quiescent`.
- **Pillar:** `prevention`, `detection`, `suppression`, `supporting`.
- **Platform:** `iss`, `drop_tower`, `other`.
- **Risk Level:** `high`, `medium`, `low`.
- **Evidence Strength:** `low`, `medium`, `high`.

---

## Latency & CORS Guarantees

1. **Strict <8.5s Latency Budget:** Upstream proxy timeout is set to `AI_PROXY_TIMEOUT_SECONDS = 8.0` so slow AI microservices fail over cleanly within 8.5 seconds, preventing client-side 10-second browser abort errors.
2. **CORS:** Allows all origins (`*`) and explicitly permits `*.vercel.app` and `http://localhost:3000` with no authentication headers required.

---

## Local Development & Testing

```bash
# Setup virtual environment
cd Backend
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
source venv/bin/activate       # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Run full automated test suite
pytest -v

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Example Invocations

### 1. Healthcheck
```bash
curl http://localhost:8000/health
```

### 2. Ask Question (Moon Base 30% O2)
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Which tested materials are risky at the Moon Base'\''s 30% oxygen?"}'
```

### 3. Ask Unanswerable Question ("Not in the data")
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the boiling point of lunar regolith tea?"}'
# Returns: {"answer": "", "grounded": false, "citations": [], "evidence": null, "latency_ms": 45.0}
```

### 4. Query Tests in Moon Base Window (28–32% O2, 9.5–11 psi)
```bash
curl "http://localhost:8000/tests?o2_min=28&o2_max=32&pressure_min=9.5&pressure_max=11"
```

### 5. Download Filtered Tests as CSV
```bash
curl -OJ "http://localhost:8000/export/csv?fuel_class=solid&o2_min=20"
```
