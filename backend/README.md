# BedSynth AI backend

FastAPI Hospital Studio, synthetic operations, validation, and analytics API using Pydantic, SQLAlchemy, and SQLite. It supports workspace-owned hospitals, departments, beds, deterministic generation runs, validation reports, and hospital-scoped analytics. It does not store real patient data or provide statistical utility/privacy-risk evaluation.

## Setup

From the repository root:

```powershell
cd backend
py -3.13 -m venv .venv313
.\.venv313\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

To install the API test tools as well, use `-m pip install -r requirements-dev.txt` instead of `requirements.txt`.

## Run

```powershell
.\.venv313\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

FastAPI loads `backend/.env` from an absolute path derived from the backend package, so environment loading does not depend on Uvicorn's `--env-file` path or the terminal's current directory. Run the command from `backend` so the default relative SQLite URL continues to use `backend/bedsynth.db`.

Health: `http://127.0.0.1:8000/health`  
Interactive API docs: `http://127.0.0.1:8000/docs`

The SQLite database defaults to `backend/bedsynth.db`. Startup creates current tables and applies a small, additive SQLite upgrade from the original foundation schema. It does not drop existing records. Existing departments with no configured capacity must have capacity set before beds can be added.

## Main routes

All routes use `/api/v1`:

- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `GET/PATCH /admin/users` and `/admin/users/{user_id}` (administrator only)
- `GET /admin/workspaces` and `PATCH /admin/workspaces/{workspace_id}/sharing` (administrator only)
- `GET /dashboard/user` (authenticated user's own runs only)
- `GET /admin/dashboard` and `GET /admin/datasets` (administrator only; run records are owner-scoped)
- `DELETE /generation-runs/{run_id}/dataset` (soft-delete an owned run; administrators are also limited to their own runs)

The client sends cookie credentials on API calls. The public `/health` endpoint remains independent of account authentication.

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
- `GET /workspaces/{workspace_id}/datasets`
- `GET /generation-runs/{run_id}/dataset`
- `GET /generation-runs/{run_id}/dataset/preview/{entity}`
- `GET /generation-runs/{run_id}/dataset/export/{entity}`
- `GET /generation-runs/{run_id}/dataset/manifest`
- `GET /analytics/hospitals/{hospital_id}/overview`
- `GET /analytics/hospitals/{hospital_id}/occupancy`
- `GET /analytics/hospitals/{hospital_id}/patient-flow`
- `GET /analytics/hospitals/{hospital_id}/departments`
- `GET /analytics/hospitals/{hospital_id}/runs`
- `GET /analytics/hospitals/{hospital_id}/insights`
- `POST /analytics/runs/compare`
- `POST /generation-runs/{run_id}/validations`
- `GET /generation-runs/{run_id}/validations`
- `GET /validations/{validation_id}`
- `POST /hospitals/{hospital_id}/departments/{department_id}/beds`
- `PATCH /hospitals/{hospital_id}/beds/{bed_id}`

Hospital archive and restore use `PATCH` with `is_archived`. Department codes are unique per hospital; bed codes are unique per hospital. Bed creation checks that its department belongs to the path hospital and has remaining configured capacity. Deletion endpoints are intentionally absent.

Bulk bed creation requires a preview followed by explicit confirmation. The preview reports non-retired inventory, remaining capacity, and the number of proposed beds per department. Confirmation includes the preview token; if inventory or capacity changed since preview, the API rejects the request and requires a fresh preview. Generated identifiers use a department-code prefix and a sequential numeric suffix, skipping any identifier already used by the hospital. New beds use category `general` and status `operational`. The batch is committed as one transaction.

Synthetic generation is deterministic and single-hospital per run. Preview accepts inclusive start/end dates, a target admission count, target occupancy percentage, seed, optional department IDs, one of five scenarios, a fictional patient profile, and length-of-stay profiles. The patient profile validates age and gender distributions to 100%, supports inclusive minimum/maximum ages, and allocates whole records with deterministic largest-remainder rounding. Length of stay is configured in days using either a fixed value or a bounded triangular minimum/mode/maximum profile. The current global synthetic default is 0.5/1/2 days; these are illustrative simulator defaults and are not empirically calibrated hospital stay statistics. Optional overrides apply only to selected departments, with the global profile as fallback. Seasonal Disease Surge applies its existing age-band multiplier and clamps the sample to the selected profile bounds. Preview uses the seeded configuration to check that arrivals and stays fit the selected bed scope without overlapping; if they cannot fit, it asks for a revised date range, bed scope, or LOS profile. This is not a waiting queue: admission and first bed assignment remain the same instant. Stays that continue beyond the inclusive observation window remain admitted, have no discharge row, and retain a bed assignment with a blank `end_at`; occupancy snapshots derive from those open-ended intervals. Historical discharge and assignment values are not inferred. Generated patients include fictional age-in-years and gender values plus the legacy age-band field; existing patient rows are retained with the new fields left null. Patient, arrival, department-demand, LOS profile, and selected scenario settings are recorded in immutable run request metadata and the preview token. Creation still requires the preview token and an idempotency UUID. The engine also creates admissions, in-window discharges, bed assignment intervals, seeded transfers, and daily noon-UTC occupancy snapshots. The current transfer policy samples one in five eligible stays of at least four observed hours when a distinct operational destination bed is available; this is a simulator rule, not a real-world rate. All generated operational rows carry workspace and hospital IDs. The run and generated rows are committed atomically after an initial `generating` history record; failures roll back generated rows and persist a failed run. This milestone does not include real patient data, names, contact data, clinical details, AI assistance, statistical utility evaluation, privacy-risk scoring, ZIP export, or asynchronous workers.

### Dataset library and exports

The user Dataset Manager lists runs owned by the authenticated user and supports hospital/status filters, search, sorting, and pagination. The administrator dataset API is retained for compatibility, but run data is scoped to the signed-in administrator's own runs; historical unowned runs remain unavailable through these ownership-checked endpoints. Soft-deleted runs are omitted by default. Run details return persisted configuration, record counts, selected departments, validation reports, and occupancy summaries from persisted snapshots. Dataset previews and exports are scoped by run, workspace, and hospital. CSV exports include available operational entities and generation-scoped bed inventory. The versioned manifest describes schema and generator versions, persisted configuration, counts, UTC timestamps, joins, and unavailable historical metadata. ZIP bundles are not provided.

### Analytics semantics and current limitations

Analytics selects the latest completed generation run for the requested hospital (ordered by completion time) by default. `run_id` selects an exact completed run and `scenario` selects the latest completed run for that scenario. The filters cannot conflict. Analytics never combines runs unless `/analytics/runs/compare` is explicitly used. The run-options endpoint returns completed run metadata, including scenario, date range, seed, profile, and included departments. Comparison accepts two to ten runs from the same hospital/workspace with the same resolved department scope; an optional common department and date range further narrow the records. The baseline defaults to the first selected run. Absolute differences are current minus baseline; percentage change is relative to baseline and is null when the baseline is zero or either value is unavailable. Patient counts are whole-run stored counts; event and occupancy metrics follow the selected period. Average length of stay is computed from admissions with valid persisted discharge timestamps, grouped by admission date. If dates are omitted, the selected run's configured reporting period is used. If supplied, `start_date` and `end_date` must both be supplied; the inclusive UTC calendar range is limited to 366 days. An optional `department_id` must belong to the hospital and, when a completed run exists, to that run's resolved department scope.

- Occupancy trends use persisted snapshots only. For each department and UTC calendar date, the latest recorded snapshot is used. Hospital daily occupancy is the sum of occupied beds divided by the sum of snapshot operational beds for the departments reporting on that date. A zero denominator produces `null`; missing snapshots are omitted rather than interpolated. The response includes department coverage for each date.
- Average occupancy is the arithmetic mean of the available, non-null daily hospital rates in the selected period; peak and lowest occupancy are their maximum and minimum. Each recorded day has equal weight. Department averages use the same equal-day weighting for each department.
- Admission counts are grouped by `admitted_at`; discharges by `discharged_at`; transfers by `transferred_at`. Department admission distribution uses the admission's initial department, and shares divide department admission counts by total admissions in the selected run/date scope. Incoming/outgoing transfers count destination/source department events. For a department filter, admissions and discharges use the admission's initial department, while a transfer is included when its source or destination department matches. Transfers remain a separate event count and are never added to admissions.
- Operational bed inventory is the current count of `operational` beds in active departments within the selected run's department scope. Latest occupied/available counts and occupancy rates come from the selected run's persisted snapshots. The schema does not version bed status or department archival state over time, so a later configuration change can make current inventory differ from the capacity recorded in historical snapshots. The dashboard labels this distinction.
- The current generator records one occupancy snapshot per department per day at 12:00 UTC. If imported or manually changed data contains multiple same-day snapshots, analytics uses the latest per department for daily charts, while the overview's snapshot total counts every persisted snapshot in range.

The insights endpoint returns deterministic rule-based observations computed only from aggregate analytics values. Relative high/low flags compare a recorded daily rate with the selected period's daily average using a 10 percentage-point rule; this is a display heuristic, not a clinical threshold. Analytics are operational summaries of a synthetic run, not statistical utility, privacy-risk, clinical quality, or model-benchmark evaluations.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./bedsynth.db` | SQLAlchemy database URL; relative SQLite paths resolve from the backend working directory. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Exact origin allowed by browser CORS. |
| `FRONTEND_ORIGINS` | Unset; falls back to `FRONTEND_ORIGIN` | Comma-separated exact browser origins for CORS and unsafe-request origin checks. |
| `APP_ENV` | `development` | Set to `production` to require secure cookie defaults and enable HSTS on HTTPS responses. |
| `SESSION_COOKIE_SAMESITE` | `lax` | Cookie SameSite mode; use `none` only with HTTPS and secure cookies for cross-site hosting. |
| `SESSION_COOKIE_SECURE` | Derived from app environment/SameSite | Explicit secure-cookie control; production and SameSite=None force secure cookies. |

### Authentication and access control

The application now uses account authentication with `admin` and `user` roles. New registrations receive the standard `user` role; extra role fields in registration are ignored, and there is no client-side administrator promotion. Passwords must be 12 to 128 characters. Bootstrap the first administrator from the backend directory with an interactive CLI (credentials are entered through prompts and are never supplied as a default):

```powershell
.\.venv313\Scripts\python.exe -m app.auth_cli create-admin
```

Then sign in at `/login`. Accounts use scrypt password hashes. Login creates an opaque random session token in an HTTP-only cookie; only its SHA-256 hash is stored in SQLite. The API does not return password hashes or session tokens. Sessions expire after 14 days and are revoked on logout or account deactivation. No credentials are stored in browser local storage.

Login failures are limited to 8 per account/IP pair and 100 per IP in a rolling 15-minute window. Registration is limited to 30 requests per IP per hour. These lightweight limits are process-local, reset on restart, and are not shared by multiple workers; use a trusted reverse-proxy or edge rate limiter for a multi-worker public deployment. Client IPs are taken from the direct ASGI connection, not blindly trusted forwarding headers. The API adds `nosniff`, frame, referrer, and permissions headers; API responses use `Cache-Control: no-store`. HSTS is returned only for production HTTPS requests. The Next.js frontend applies corresponding browser security headers.

Hospital visibility is controlled by the Available to users setting in Hospital Management. The legacy workspace-sharing CLI remains for compatibility, but workspace sharing does not publish hospitals to normal users.

```powershell
.\.venv313\Scripts\python.exe -m app.auth_cli share-workspace <workspace-id>
```

Administrators manage hospitals, departments, and beds, then explicitly publish each active hospital for user selection. Standard users see active published hospitals and can access, export, compare, validate, or soft-delete only their own runs. Historical runs without an owner remain preserved and inaccessible through user dataset routes; they are never assigned to an account automatically. Backend checks enforce these rules.

Cookie settings are controlled by `APP_ENV`, `SESSION_COOKIE_SAMESITE`, and `SESSION_COOKIE_SECURE`. Local development defaults to `SameSite=Lax` and insecure cookies for localhost HTTP. For a cross-site hosted frontend/backend, configure `SESSION_COOKIE_SAMESITE=none` and `SESSION_COOKIE_SECURE=true` and set `FRONTEND_ORIGINS` to the exact permitted browser origins (comma-separated). Never use wildcard CORS origins with credentials. Unsafe API requests enforce the configured Origin allowlist; credentialed unsafe requests without an Origin are rejected.

GET /dashboard/user returns counts and recent activity for completed, non-deleted runs owned by the current user. It derives latest occupancy from that user's latest completed run with snapshots. GET /admin/dashboard includes account and hospital summary counts; generation-run and generated-row metrics include only the signed-in administrator's own runs. GET /admin/datasets lists only that administrator's runs. These endpoints require an authenticated session.

Authentication tables are created additively. SQLite receives nullable `generation_runs.owner_user_id` and `deleted_at` columns and a default-private `workspaces.is_shared` column. Existing generation runs retain a null owner; no run is migrated to a new account. Soft deletion sets `deleted_at` and keeps all operational records. Use a database backup under your normal operational backup procedure before deploying schema changes.

### Hospital publishing and legacy data

Administrators publish an active hospital through Hospital Management using **Available to users**. Normal-user hospital catalogue and generation requests are limited to active, published configurations. Dataset details, exports, analytics, validation, and deletion are owner-scoped for all registered accounts, including administrators. Guest access and the AI Assistant are retired from the active API. Existing guest-session tables, guest ownership columns, and historical guest runs are retained; startup does not run guest-session cleanup, and legacy guest data is excluded from registered-user dataset access.
