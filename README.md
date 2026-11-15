# BedSynth AI

BedSynth AI is a synthetic hospital operations data platform for exercising bed occupancy and scheduling workflows with fictional, reproducible datasets. The current application is an MVP foundation and does not use real patient records.

## Current application

- **Frontend:** Next.js App Router, React, TypeScript, Tailwind CSS, Recharts, and Lucide.
- **Backend:** FastAPI, Pydantic, SQLAlchemy, and SQLite.
- **Generation:** deterministic, hospital-scoped generation with five scenarios, configurable fictional age/gender profiles, a preview and validation step, explicit confirmation, preview freshness checks, and idempotency.
- **Other features:** workspace and hospital configuration, bulk bed creation, dataset history/details/CSV export, data validation, operational analytics, and an optional Gemini configuration assistant.

See [backend/README.md](backend/README.md) for the API routes, generation and analytics semantics, database notes, and environment variables. The approved hospital domain is documented in [HOSPITAL_DOMAIN_SPECIFICATION.md](docs/architecture/HOSPITAL_DOMAIN_SPECIFICATION.md).

## Prerequisites

- Python 3.11 or newer supported by the installed project dependencies.
- Node.js and npm compatible with the installed Next.js 15 project.
- Git.
- A Google Gemini API key is optional and only needed for the assistant. The standard generator does not require it.

## Local setup

Create the backend environment and install the declared runtime and test dependencies:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `backend/.env` locally only if configuration needs to change. `GEMINI_API_KEY` is optional, must remain backend-only, and should never be committed. Do not put credentials in any `NEXT_PUBLIC_*` variable. By default, SQLite uses `backend/bedsynth.db`; run the backend from `backend` so its relative database path is predictable. The application initializes missing tables and has a small additive upgrade for its original schema. Do not delete the database to troubleshoot or upgrade.

In a separate terminal, install frontend dependencies and prepare its local environment:

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
```

`NEXT_PUBLIC_API_BASE_URL` is a browser-visible URL (default `http://localhost:8000`), never a place for a secret.

## Run locally

Start the backend from its directory:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend from another terminal:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:3000`. Backend health is available at `http://127.0.0.1:8000/health`; interactive API documentation is at `http://127.0.0.1:8000/docs`.

## Verification

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

From `frontend`:

```powershell
npm run build
```

The backend test suite uses an isolated temporary database. Do not point it at the local application database. The production build writes to the configured Next.js build output directory and does not change application data.

## Important workflow and data boundaries

1. Configure a hospital, departments, and operational bed inventory in Hospital Studio.
2. Configure a generation period, scenario, patient profile, and seed in Generator.
3. Request a generation preview and review its scope and validation results.
4. Confirm separately. The backend checks the preview token against the current configuration and uses an idempotency key before persisting a run.
5. Inspect generated datasets, validation reports, and operational analytics.

The assistant only proposes and validates generation configuration; it does not create records. Its handoff still goes through Generator preview and separate confirmation. Do not send patient information to the assistant. The current high-signal text filter is not a general-purpose PHI detector.

## Security and scope limitations

The current application has no authentication or authorization. Workspace and hospital IDs scope data relationships and route queries, but IDs do not prove that a caller is entitled to access a workspace. Do not expose this application as a multi-user or production service until identity, authorization, tenant isolation, deployment secret management, and operational controls are implemented and reviewed.

Generated patients and operational events are fictional. Current analytics are operational summaries of synthetic data; they are not clinical quality measures, statistical utility evaluations, privacy-risk evaluations, or evidence that a scheduling model is safe or effective. Cross-hospital generation orchestration, asynchronous jobs, statistical utility/privacy-risk scoring, and model benchmarking are not current capabilities.

## Repository map

```text
backend/    FastAPI application, SQLAlchemy models, services, and tests
frontend/   Next.js application and UI
docs/       Product and architecture documentation
```

There is no authentication service, external job queue, or deployment configuration in the current MVP. See the backend guide for the complete current API surface and known analytics/generation semantics.
