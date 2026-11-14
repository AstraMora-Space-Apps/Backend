# FlameSight Backend — BFF API Gateway

> **NASA Space Apps Challenge 2026**  
> *Challenge Track:* Flame in Freefall (Virtual Track)  
> *Version:* `v0.1-hackathon`  
> *Status:* `v0.1, unverified extraction`

FlameSight Backend is the production-ready **Backend-for-Frontend (BFF) API Gateway** built with **FastAPI**. It powers the FlameSight mission interface by serving structured microgravity combustion research from the NASA Physical Sciences Informatics (PSI) repository, evaluating exploration habitat environmental proximity metrics, and asynchronously proxying natural language queries to the AI RAG microservice with automatic failover, strict latency budgeting (<8.5s), and in-memory TTL caching.

---

## 1. Preliminary Data Notice

> [!WARNING]
> **Data Status: `v0.1, unverified extraction`**  
> All experimental test records, material flammability limits, and risk insights served by this repository represent preliminary research extractions curated during the NASA Space Apps Challenge 2026 hackathon. These values are intended for research demonstration and conceptual engineering exploration only. They have **not** undergone formal NASA flight-qualification peer review and must not be used as operational flight criteria or safety-critical spacecraft ECLSS controls.

---

## 2. System Architecture

FlameSight operates as a decoupled three-service microservices architecture:

```text
┌────────────────────────────────────────────────────────┐
│                   FlameSight Frontend                  │
│       Next.js 15 (App Router) + Tailwind CSS + Plotly  │
│  Repository: https://github.com/AstraMora-Space-Apps/Frontend
└───────────────────────────┬────────────────────────────┘
                            │ REST JSON over HTTP (CORS Enabled)
                            ▼
┌────────────────────────────────────────────────────────┐
│             FlameSight Backend API (This Repo)         │
│          FastAPI BFF Gateway (Port 8000)               │
│                                                        │
│  • Strict <8.5s Latency Budget & In-Memory TTL Cache   │
│  • Dual-Mode SQLite Reader + NASA PSI Seed Fallback    │
│  • Range Overlap & Inclusive Within Query Evaluators   │
│  • Gas/Solid Fuel Class Combustion Separation Guardrail│
└───────────────────────────┬────────────────────────────┘
                            │ POST /ask (<8.0s timeout)
                            ▼
┌────────────────────────────────────────────────────────┐
│                  flamesight AI Service                 │
│         ChromaDB Vector Embeddings + RAG Pipeline      │
│  Repository: https://github.com/AstraMora-Space-Apps/flamesight
└────────────────────────────────────────────────────────┘
```

### Sibling Repositories
- **Frontend Dashboard:** [https://github.com/AstraMora-Space-Apps/Frontend](https://github.com/AstraMora-Space-Apps/Frontend)
- **AI / RAG Microservice:** [https://github.com/AstraMora-Space-Apps/flamesight](https://github.com/AstraMora-Space-Apps/flamesight)

---

## 3. NASA Data Sources & Attribution

All experimental parameters, flammability limits, and source quotations are grounded in open NASA research available through:
- **NASA Physical Sciences Informatics (PSI) Repository:** [https://psi.nasa.gov/](https://psi.nasa.gov/)
- **NASA Technical Reports Server (NTRS):** [https://ntrs.nasa.gov/](https://ntrs.nasa.gov/)

### Primary Flight Investigations Included:
1. **BASS & BASS-II** (*Burning and Suppression of Solids* — [PSI-26](https://psi.nasa.gov/physci/repo/data/investigations/PSI-26)): Low-speed opposed/concurrent forced flow flame spread and extinction limits across solid fabrics and PMMA in the Microgravity Science Glovebox (MSG).
2. **Saffire I, II & III** (*Spacecraft Fire Safety Experiments* — [PSI-35](https://psi.nasa.gov/physci/repo/data/investigations/PSI-35)): Large-scale ($0.4\text{ m} \times 1.0\text{ m}$) fabric burns conducted inside departing Cygnus cargo spacecraft.
3. **SoFIE** (*Solid Fuel Ignition and Extinction* — [PSI-42](https://psi.nasa.gov/physci/repo/data/investigations/PSI-42)): Material flammability, ignition delays, and quench boundaries in exploration atmospheres (up to $30\%\text{ O}_2$ at $10.2\text{ psi}$).
4. **SAME & SAME-R** (*Smoke Aerosol Measurement Experiment* — [PSI-15](https://psi.nasa.gov/physci/repo/data/investigations/PSI-15)): Particulate size distributions and smoke agglomeration signatures from pyrolyzing wire insulation in microgravity.
5. **FLEX & FLEX-2** (*Flame Extinguishment Experiment* — [PSI-18](https://psi.nasa.gov/physci/repo/data/investigations/PSI-18)): Spherically symmetric liquid droplet combustion, suppression dynamics, and low-temperature "cool flame" burning.
6. **ACME BRE & CFI-G** (*Advanced Combustion via Microgravity Experiments* — [PSI-10](https://psi.nasa.gov/physci/repo/data/investigations/PSI-10), [PSI-20](https://psi.nasa.gov/physci/repo/data/investigations/PSI-20)): Gaseous diffusion flames and burning rate emulation across porous circular burners.

---

## 4. AI Disclosure & Branding Compliance

### Use of Artificial Intelligence (AI / SI)
Artificial intelligence coding assistants (including Google Antigravity, Claude, and Gemini) were utilized during the hackathon to assist in accelerating API scaffolding, test generation, schema normalization, and prompt engineering. Scientific finding summaries and citations were cross-verified against NASA PSI source documents.

### NASA Branding & Mark Compliance
In strict adherence to NASA Space Apps Challenge regulations:
- **No NASA insignia, logos, meatball marks, worm logos, flags, or mission patches** are displayed or embedded within this repository, its assets, or its endpoints.
- The project is an independent submission developed by Team AstraMora for the NASA Space Apps Challenge 2026.

---

## 5. Endpoints & REST Contract

| Method | Endpoint | Query Parameters | Response Shape | Description |
|---|---|---|---|---|
| `GET` | `/health` | None | `HealthResponse` | Returns `{ status: "ok", version: "v0.1-hackathon", sqlite_connected: bool, ai_service_configured: bool, disclaimer: "v0.1, unverified" }`. |
| `POST` | `/ask` | None (JSON body: `{"question": string}`) | `AskResponse` | Natural language question proxy. If `grounded` is `false`, `answer` is strictly `""`, `citations: []`, and `evidence: null`. |
| `POST` | `/cache/clear` | None | `dict` | Clears all entries from the in-memory `/ask` TTL cache. |
| `GET` | `/investigations` | `fuel_class`, `hardware`, `pillar`, `o2_min`, `o2_max`, `pressure_min`, `pressure_max`, `q` | `Investigation[]` (raw array) | Filters investigations where parameter ranges **overlap** (`cond.max >= filter_min and cond.min <= filter_max`). |
| `GET` | `/tests` | `investigation_id`, `fuel_class`, `hardware`, `pillar`, `o2_min`, `o2_max`, `pressure_min`, `pressure_max`, `q` | `TestRecord[]` (raw array) | Filters test observations where scalar values are **inclusive within** (`filter_min <= val <= filter_max`). |
| `GET` | `/insights` | None | `Insight[]` (raw array) | Ranked safety insights sorted strictly descending by `score = safety_impact * evidence_strength * mission_relevance` (1 to 125). |
| `GET` | `/export/csv` | Same query params as `/tests` | `text/csv` stream | Streams `flamesight_per_test_v0.1_unverified.csv` with the header `# FlameSight Per-Test Dataset (v0.1, unverified extraction - NASA Space Apps 2026)`. |

### Physical Units Standard
- **Total Pressure:** Always expressed in **psi** (e.g. `14.7` standard Earth/ISS, `10.2` Moon Base, `4.3` Spacesuit).
- **Oxygen Concentration:** Always expressed in **volume/mole percent (%)** (e.g. `21.0` Earth, `30.0` Exploration Atmosphere).
- **Flame Spread Rate:** Always expressed in **mm/s**.
- **Ventilation Velocity:** Always expressed in **cm/s**.

---

## 6. Environment Variables

| Variable | Default Value | Description |
|---|---|---|
| `AI_SERVICE_URL` | `""` (empty) | URL of upstream `flamesight` RAG microservice. If empty or unreachable, backend falls back cleanly to verified grounded stub literature. |
| `DB_PATH` | `data/flamesight.db` | Path to SQLite database. Automatically falls back to seed data if file or tables are not present. |
| `CACHE_TTL_SECONDS` | `300` | In-memory query response caching time-to-live in seconds. |
| `AI_PROXY_TIMEOUT_SECONDS` | `8.0` | Upstream proxy timeout in seconds (strictly <8.5s to fit within frontend's 10s client timeout). |
| `ALLOWED_ORIGINS` | `"*"` | CORS allowed origins (also explicitly permits `*.vercel.app` and `localhost`). |
| `PORT` | `8000` | HTTP listening port for uvicorn. |

---

## 7. Local Setup & Docker Deployment

### Local Development
```bash
# Navigate to Backend folder
cd Backend

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows PowerShell
source venv/bin/activate       # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Run automated test suite
pytest -v

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker Run
```bash
# Build container image
docker build -t flamesight-backend:latest .

# Run container (supports dynamic $PORT)
docker run -p 8000:8000 -e PORT=8000 flamesight-backend:latest
```

### Render Deployment
This repository includes a `render.yaml` blueprint. When linked to Render, it configures:
```yaml
startCommand: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
healthCheckPath: /health
```
