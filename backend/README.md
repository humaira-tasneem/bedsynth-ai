# BedSynth AI backend

FastAPI Hospital Studio API using Pydantic, SQLAlchemy, and SQLite. It supports workspaces, optional hospital networks, hospitals, departments, and beds. There are no patient records, synthetic generation, or analytics endpoints.

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
- `POST /hospitals/{hospital_id}/departments/{department_id}/beds`
- `PATCH /hospitals/{hospital_id}/beds/{bed_id}`

Hospital archive and restore use `PATCH` with `is_archived`. Department codes are unique per hospital; bed codes are unique per hospital. Bed creation checks that its department belongs to the path hospital and has remaining configured capacity. Deletion endpoints are intentionally absent.

Bulk bed creation requires a preview followed by explicit confirmation. The preview reports non-retired inventory, remaining capacity, and the number of proposed beds per department. Confirmation includes the preview token; if inventory or capacity changed since preview, the API rejects the request and requires a fresh preview. Generated identifiers use a department-code prefix and a sequential numeric suffix, skipping any identifier already used by the hospital. New beds use category `general` and status `operational`. The batch is committed as one transaction.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./bedsynth.db` | SQLAlchemy database URL; relative SQLite paths resolve from the backend working directory. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Exact origin allowed by browser CORS. |

This foundation has no authentication yet. Workspace scoping is enforced by route/resource relationships, but access control must be added before exposing it to multiple users or networks.
