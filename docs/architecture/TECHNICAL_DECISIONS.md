# BedSynth AI Technical Decisions

**Status:** Proposed decision record for planning. Choices require validation during implementation; no technology is asserted to be installed or in use.

## Decision summary

| Area | Proposed choice | State |
|---|---|---|
| Web UI | Next.js, React, TypeScript | Proposed |
| Styling/components | Tailwind CSS, shadcn/ui | Proposed |
| API | Python, FastAPI, Pydantic | Proposed |
| Relational metadata | PostgreSQL, SQLAlchemy, Alembic | Proposed |
| Data processing | Pandas, NumPy | Proposed |
| Synthetic methods | SDV plus suitable statistical/generative methods | Selection open by data/table |
| Prompt interpretation | Gemini API with structured outputs | Proposed; privacy and model selection open |
| Charts | Recharts | Proposed |
| Testing | Pytest, Vitest, Playwright | Proposed |
| Hosting | Vercel plus Render or Railway | Provider/topology open |
| Source control | Git and GitHub | Direction supplied; repository workflow unspecified |

## Technology choices and alternatives

### Next.js, React, TypeScript

**Reason:** Mature component-based ecosystem, typed UI contracts, routing, and hosting options aligned with a responsive SaaS interface.  
**Alternatives considered:** React with another routing/build setup; a Python-rendered UI.  
**Trade-offs:** Adds a separate JavaScript toolchain and requires clear API type synchronization. Server rendering is not automatically needed for an authenticated data tool; choose rendering features based on actual UX needs.

### Tailwind CSS and shadcn/ui

**Reason:** Supports token-driven styling and reusable accessible component patterns while allowing product-specific visual ownership.  
**Alternatives considered:** CSS Modules/design-system package; a fully prebuilt component suite.  
**Trade-offs:** shadcn/ui components are copied/owned in the application and must be maintained; Tailwind conventions require team consistency. Accessibility still requires implementation and testing.

### FastAPI and Pydantic

**Reason:** Python-native API contracts and validation fit the proposed Python data-generation stack and provide a clear boundary for structured requests.  
**Alternatives considered:** Django REST Framework; Flask; a TypeScript backend.  
**Trade-offs:** FastAPI does not by itself provide a complete identity, job, or authorization system. Those concerns need explicit choices and controls.

### PostgreSQL, SQLAlchemy, Alembic

**Reason:** Relational integrity suits accounts, hospital configuration, job metadata, and dataset manifests; SQLAlchemy and Alembic support model mapping and schema evolution.  
**Alternatives considered:** SQLite for a local prototype; document database; storing all data as files.  
**Trade-offs:** PostgreSQL is not automatically the best place for every generated row at scale. The output storage design remains open pending volume, query, retention, and hosting validation.

### Pandas and NumPy

**Reason:** Familiar tools for tabular manipulation, statistics, and prototyping synthesis/validation workflows.  
**Alternatives considered:** Polars or database-native processing for larger data; specialized distributed computation.  
**Trade-offs:** In-memory processing can constrain dataset size and concurrency. Benchmark with representative workloads before selecting a scaling strategy; do not add distributed infrastructure preemptively.

### SDV and statistical/generative methods

**Reason:** SDV is a candidate toolkit for tabular synthetic data, while rule-based/statistical methods may better express hard operational constraints and event sequences. A hybrid per-table approach may be appropriate.  
**Alternatives considered:** Rule-based-only generation; custom probabilistic models; other tabular synthesis libraries.  
**Trade-offs:** A learned tabular model does not inherently guarantee temporal, referential, capacity, or privacy properties. Method choice, fit data policy, constraints, and evaluation must be validated per table. No quality claim follows from library selection alone.

### Gemini structured outputs

**Reason:** A structured response can translate natural language into a constrained configuration proposal while keeping synthesis deterministic and independently validated.  
**Alternatives considered:** Manual configuration only; another hosted LLM; a local model.  
**Trade-offs:** Provider availability, cost, latency, data handling, version drift, and prompt-injection risks require review. Structured output reduces formatting errors but does not establish correctness. Manual entry must remain available.

### Recharts

**Reason:** React-native chart composition aligns with the proposed frontend and allows styling from product tokens.  
**Alternatives considered:** Visx, ECharts, static chart rendering.  
**Trade-offs:** Charts require accessible summaries and alternatives; library output needs dark-theme, responsive, and keyboard review.

### Pytest, Vitest, Playwright

**Reason:** Separate layers for Python unit/integration checks, TypeScript UI logic, and end-to-end browser journeys.  
**Alternatives considered:** Other framework-specific tools.  
**Trade-offs:** Multiple test runners add maintenance. Scope test layers to risk and keep API contract/invariant tests authoritative for generation behavior.

### Vercel with Render or Railway

**Reason:** Candidate managed hosting direction for frontend and Python service/database with relatively direct deployment workflows.  
**Alternatives considered:** Single cloud provider, container platform, self-managed infrastructure.  
**Trade-offs:** Cross-provider networking, logs, backups, secrets, regions, background workers, cost, and operational responsibility need review. No provider should be selected solely from framework compatibility.

## Architectural decisions

1. **Separate prompt interpretation from generation.** The LLM proposes structured settings; validated application code controls job execution.
2. **Snapshot configuration per run.** Later edits must not change the provenance of a completed dataset.
3. **Validate outputs after generation.** Hard structural and operational invariants are checked independently of the synthesis algorithm.
4. **Use event records as the likely canonical operational history.** Occupancy is derived/materialized only with a documented formula and version; final choice requires domain review.
5. **Represent long-running work as persisted jobs.** Queue/worker implementation is deferred until workload and host capabilities are known.
6. **Treat generated row storage as an open architecture decision.** PostgreSQL is proposed for metadata, but large immutable outputs may warrant object storage.
7. **Keep synthetic-data claims bounded.** A generated dataset is not presumed representative, unbiased, private, or suitable for a clinical purpose.

## Decisions requiring future validation

- Identity provider/session strategy, workspace tenancy, and role model.
- Hospital event definitions, occupancy denominator/cadence, and exception semantics with domain experts.
- Which tables and columns are in the first schema; whether synthetic subject identifiers are needed.
- Generation method for each table and strategy for cross-table constraints.
- Fit-data sourcing and governance for any learned model; privacy risk evaluation approach.
- Gemini model/version, regional processing, retention terms, prompt logging, and cost controls.
- Output storage, maximum dataset size, export format, retention, deletion, and backup strategy.
- Background jobs, retries, concurrency limits, and deployment topology.
- Time-zone behavior and numeric performance/availability objectives.
- Whether scenario simulation or benchmarking needs external model execution; define safe interface and metric protocol.
- Accessibility verification process and supported browser/device targets.
