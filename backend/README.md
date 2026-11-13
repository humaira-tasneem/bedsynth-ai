# BedSynth AI backend

FastAPI Hospital Studio, synthetic operations, validation, and analytics API using Pydantic, SQLAlchemy, and SQLite. It supports workspace-owned hospitals, departments, beds, deterministic generation runs, validation reports, and hospital-scoped analytics. It does not store real patient data or provide statistical utility/privacy-risk evaluation.

## Setup

From the repository root:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

To install the API test tools as well, use `-m pip install -r requirements-dev.txt` instead of `requirements.txt`.

## Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --env-file .env --host 127.0.0.1 --port 8000
```

Health: `http://127.0.0.1:8000/health`  
Interactive API docs: `http://127.0.0.1:8000/docs`

The SQLite database defaults to `backend/bedsynth.db`. Startup creates current tables and applies a small, additive SQLite upgrade from the original foundation schema. It does not drop existing records. Existing departments with no configured capacity must have capacity set before beds can be added.

## Main routes

All routes use `/api/v1`:

- `GET/POST /workspaces`
- `GET/POST /workspaces/{workspace_id}/networks`
- `GET/POST /workspaces/{workspace_id}/hospitals`
- `GET/PATCH /workspaces/{workspace_id}/hospitals/{hospital_id}`
- `GET/POST /hospitals/{hospital_id}/departments`
- `PATCH /hospitals/{hospital_id}/departments/{department_id}`
- `GET /hospitals/{hospital_id}/beds`
- `POST /hospitals/{hospital_id}/beds/generation-preview`
- `POST /hospitals/{hospital_id}/beds/generate`
- `POST /hospitals/{hospital_id}/generation-runs/preview`
- `POST /hospitals/{hospital_id}/generation-runs`
- `GET /workspaces/{workspace_id}/generation-runs`
- `GET /analytics/hospitals/{hospital_id}/overview`
- `GET /analytics/hospitals/{hospital_id}/occupancy`
- `GET /analytics/hospitals/{hospital_id}/patient-flow`
- `GET /analytics/hospitals/{hospital_id}/departments`
- `POST /generation-runs/{run_id}/validations`
- `GET /generation-runs/{run_id}/validations`
- `GET /validations/{validation_id}`
- `POST /hospitals/{hospital_id}/departments/{department_id}/beds`
- `PATCH /hospitals/{hospital_id}/beds/{bed_id}`

Hospital archive and restore use `PATCH` with `is_archived`. Department codes are unique per hospital; bed codes are unique per hospital. Bed creation checks that its department belongs to the path hospital and has remaining configured capacity. Deletion endpoints are intentionally absent.

Bulk bed creation requires a preview followed by explicit confirmation. The preview reports non-retired inventory, remaining capacity, and the number of proposed beds per department. Confirmation includes the preview token; if inventory or capacity changed since preview, the API rejects the request and requires a fresh preview. Generated identifiers use a department-code prefix and a sequential numeric suffix, skipping any identifier already used by the hospital. New beds use category `general` and status `operational`. The batch is committed as one transaction.

Synthetic generation is deterministic and single-hospital per run. Preview accepts inclusive start/end dates, a target admission count, target occupancy percentage, seed, and optional department IDs. Creation requires the preview token and an idempotency UUID. The engine creates only fictional patient IDs and age bands, admissions, discharges, bed assignment intervals, seeded transfers, and daily noon-UTC occupancy snapshots. The current transfer policy samples one in five eligible stays of at least four hours when a distinct operational destination bed is available; this is a simulator rule, not a real-world rate. All generated operational rows carry workspace and hospital IDs. The run and generated rows are committed atomically after an initial `generating` history record; failures roll back generated rows and persist a failed run. This milestone does not include real patient data, clinical details, Gemini/RAG, statistical utility evaluation, privacy-risk scoring, export, or asynchronous workers.

### Analytics semantics and current limitations

Analytics selects the latest completed generation run for the requested hospital (ordered by completion time). It does not combine runs: separate runs are separate synthetic scenarios and can cover overlapping dates. Responses identify the selected run and seed. If dates are omitted, the run's configured reporting period is used. If supplied, `start_date` and `end_date` must both be supplied; the inclusive UTC calendar range is limited to 366 days. An optional `department_id` must belong to the hospital and, when a completed run exists, to that run's resolved department scope.

- Occupancy trends use persisted snapshots only. For each department and UTC calendar date, the latest recorded snapshot is used. Hospital daily occupancy is the sum of occupied beds divided by the sum of snapshot operational beds for the departments reporting on that date. A zero denominator produces `null`; missing snapshots are omitted rather than interpolated. The response includes department coverage for each date.
- Average occupancy is the arithmetic mean of the available, non-null daily hospital rates in the selected period; peak occupancy is their maximum. Each recorded day has equal weight.
- Admission counts are grouped by `admitted_at`; discharges by `discharged_at`; transfers by `transferred_at`. For a department filter, admissions and discharges use the admission's initial department, while a transfer is included when its source or destination department matches. Transfers remain a separate event count and are never added to admissions.
- Operational bed inventory is the current count of `operational` beds in active departments within the selected run's department scope. Latest occupied/available counts and occupancy rates come from the selected run's persisted snapshots. The schema does not version bed status or department archival state over time, so a later configuration change can make current inventory differ from the capacity recorded in historical snapshots. The dashboard labels this distinction.
- The current generator records one occupancy snapshot per department per day at 12:00 UTC. If imported or manually changed data contains multiple same-day snapshots, analytics uses the latest per department for daily charts, while the overview's snapshot total counts every persisted snapshot in range.

Analytics are operational summaries of a synthetic run. They are not statistical utility, privacy-risk, clinical quality, or model-benchmark evaluations.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./bedsynth.db` | SQLAlchemy database URL; relative SQLite paths resolve from the backend working directory. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Exact origin allowed by browser CORS. |

This foundation has no authentication yet. Workspace scoping is enforced by route/resource relationships, but access control must be added before exposing it to multiple users or networks.
