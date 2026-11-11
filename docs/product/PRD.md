# BedSynth AI Product Requirements Document

**Status:** Proposed product plan; capabilities in this document are not claims about implemented software.  
**Audience:** Product, design, engineering, and reviewers.  
**Product:** BedSynth AI, an AI-assisted synthetic hospital operations data platform.

## Product vision

Enable teams to configure a virtual hospital and generate reproducible, structurally coherent synthetic operational datasets for developing and testing bed-occupancy and scheduling models. The product should make assumptions visible and provide tools to inspect, evaluate, analyze, simulate, and export generated data. Synthetic records are for development and testing, not clinical decision-making or a substitute for approved real-world evidence.

## Problem statement

Hospital operations data is difficult to obtain, share, and prepare for model development. Teams may lack data that is safe to use in development, internally consistent across admissions, beds, transfers, and discharges, or tailored to a particular operating scenario. Generic sample data rarely reflects a facility's constraints. BedSynth AI is intended to let users define those constraints, generate linked tables, and inspect the resulting dataset before using it elsewhere.

This product does not assert that generated data is representative of a particular hospital or population. Users must be able to distinguish configured assumptions from observed facts and assess suitability for each downstream use.

## Target users

- **Operations analyst / data scientist:** creates datasets to explore occupancy and scheduling models.
- **Operations researcher / optimization engineer:** tests capacity, allocation, and scheduling logic under controlled scenarios.
- **Healthcare technology engineer:** builds integrations and needs repeatable fixtures for pipelines and applications.
- **Educator / researcher:** demonstrates operational analytics with explicitly synthetic examples.
- **Workspace administrator:** manages virtual hospital configuration and access for a team (team administration is an advanced scope).

## Product objectives

1. Allow users to define a virtual hospital's operational structure and constraints.
2. Generate coherent, related operational tables from a saved configuration and generation request.
3. Provide transparent quality checks and descriptive analysis before export.
4. Make generation settings and outputs reproducible through versioned metadata and history.
5. Support scenario-based testing and model benchmarking as staged capabilities.
6. Present a professional, accessible, responsive interface consistent with the Clinical Modern design direction.

### Non-goals

- Production hospital information system or electronic health record.
- Patient care, diagnosis, triage, or clinical recommendations.
- Claiming synthetic records are anonymous, non-identifiable, unbiased, or statistically faithful without a defined and validated method.
- Connecting to live hospital systems in the MVP.
- Replacing specialist statistical review or a user's validation of model suitability.

## Functional requirements

### Hospital configuration

- Create, view, edit, and archive a virtual hospital within the user's workspace.
- Configure departments, bed inventory, bed types/statuses, and operational parameters used by generation.
- Validate configuration references (for example, each bed belongs to a valid department) and explain invalid or conflicting settings.
- Save configuration revisions or otherwise preserve the exact configuration snapshot used by each generation.
- Keep optional constraints explicit, including capacity limits, service/department relationships, and supported time windows. Exact constraint vocabulary requires domain validation.

### Generation and linked data

- Generate a selected set of related tables, initially centered on admissions, discharges, transfers, occupancy intervals/snapshots, and optional waiting-list records.
- Accept a time range, target volume or generation scale, random seed, hospital configuration revision, and selected operational constraints.
- Apply deterministic generation for a fixed seed and unchanged versioned inputs where supported; record generator/model versions and any nondeterministic dependency.
- Maintain referential integrity and temporal consistency across generated records. A discharge must follow its admission; transfer events must refer to valid stays and destinations; occupancy must not exceed configured capacity unless an explicitly modeled exception permits it.
- Show progress and recoverable failure state for long-running jobs. Do not expose partially successful output as a completed dataset without a clear status and completeness indication.
- Save generation configuration and dataset metadata for each run.

### Natural-language assistant

- Accept user prompts describing a desired operational scenario and translate them into a proposed structured generation configuration.
- Display the interpretation and validation issues for user review before starting generation.
- Use Gemini structured outputs for the planning response; validate the response against application schemas and never execute arbitrary instructions or code from model output.
- Communicate uncertainty and avoid implying that prompt interpretation is a clinical recommendation.
- Offer a non-GenAI path to configure the same options manually.

### Quality evaluation

- Report structural checks (required fields, types, keys, references, allowed values) and operational checks (time ordering, capacity rules, linked event consistency).
- Report descriptive statistics and distributions against configured targets where targets exist.
- Distinguish a passed invariant from a statistical similarity assessment. Show the metric, scope, reference/target, and threshold when applicable.
- Provide warnings and actionable explanations; do not label a dataset “realistic” solely from schema validity.
- Record evaluation method/version and results with the dataset.

### Analysis and preview

- Preview tables with pagination and column/type information; protect against rendering the entire dataset in the browser.
- Provide summary counts and time-series visualizations such as occupancy by department, subject to a clearly defined occupancy calculation.
- Allow filtering by date range and supported operational dimensions.
- Clearly label all examples and charts as synthetic and show relevant configuration context.

### Scenario simulation (advanced)

- Let users define controlled changes to capacity, demand, arrival patterns, or other supported parameters and generate comparable scenario runs.
- Preserve scenario inputs and allow side-by-side comparison of output indicators.
- Define simulation semantics and operational assumptions before implementation; avoid unbounded free-form simulation claims.

### Export and reproducibility

- Export selected tables in agreed formats (CSV is the initial baseline; Parquet may be considered after operational validation).
- Include a manifest with dataset/run identifiers, schema version, generation inputs, seed when used, timestamps, and quality summary.
- Ensure exports use stable, documented column names and data types.
- Provide generation history, statuses, configuration snapshots, and links to previews/exports.

### Model benchmarking (advanced)

- Support user-provided model outputs or a bounded set of documented evaluation workflows; the product must define the interface before implementation.
- Report metrics with definitions, split strategy, dataset/scenario references, and limitations.
- Do not claim model performance transfers to real hospital operations.

## Non-functional requirements

- **Accessibility:** Target WCAG 2.2 AA, including keyboard operation, visible focus, semantic structure, sufficient contrast, and accessible chart alternatives.
- **Responsive design:** Support desktop, tablet, and mobile layouts; dense data tables may use an explicitly designed compact or horizontal-scroll treatment on narrow screens.
- **Reliability:** Persist generation status and enough metadata to diagnose and resume or safely retry supported jobs.
- **Security:** Authenticate users before storing private workspace data; enforce authorization at every API boundary; protect secrets; encrypt network traffic and use platform storage encryption where available.
- **Privacy and disclosure:** Use synthetic labels in UI and exports. Do not accept or encourage real patient identifiers for the proposed MVP. Define retention and deletion behavior before launch.
- **Performance:** Establish measurable targets through product and workload discovery before committing service-level claims. Paginate previews and execute generation/analysis as background work when needed.
- **Reproducibility:** Version schemas, generation configuration, generator implementation, and quality methods represented in run metadata.
- **Observability:** Capture operational logs and job failures without logging prompt content or dataset rows unnecessarily; define retention and access controls.
- **Maintainability:** Use typed API contracts, migrations, modular generation and validation boundaries, and automated tests in implementation phases.

## Core and advanced features

| Core (MVP proposal) | Advanced (later phases) |
|---|---|
| Workspace account and one or more virtual hospitals | Multi-user roles and team administration |
| Departments, beds, and basic capacity constraints | Rich constraint templates and policy variants |
| Linked operational table generation | Alternative statistical/generative model strategies |
| Optional prompt-to-configuration assistant with review | Iterative conversational refinement and saved prompt templates |
| Structural and operational quality checks | Calibrated statistical evaluation and privacy-risk assessment |
| Dataset preview, summary analytics, CSV export | Parquet/large-scale export and external integrations |
| Run history, seed, and configuration snapshot | Scenario comparison and model benchmarking |

## Key user journeys

### Configure and generate

1. User signs in and creates a virtual hospital.
2. User defines departments, beds, and supported operational constraints.
3. System validates the configuration and identifies missing or contradictory inputs.
4. User chooses tables, date range, scale, and seed, or asks the assistant to draft these settings.
5. User reviews the resolved structured configuration and starts a run.
6. User sees job progress and a clear terminal status.
7. User inspects quality checks, analytics, and table previews.
8. User downloads the dataset and manifest or returns to run history.

### Test a scenario (advanced)

1. User selects a baseline configuration/run.
2. User changes supported parameters and reviews the differences.
3. System generates a separate run linked to the baseline and scenario definition.
4. User compares occupancy and other agreed indicators, with assumptions visible.

### Reproduce a run

1. User opens generation history and selects a completed run.
2. System displays saved configuration, schema/generator versions, seed, and quality method.
3. User requests a rerun using the preserved inputs, where supported, and can compare resulting manifests.

## MVP scope

The MVP should prove the end-to-end workflow for a single authenticated user or private workspace: configure a virtual hospital, generate a bounded linked dataset, validate it, inspect summary charts and paginated rows, export CSV with a manifest, and revisit run history. The assistant may be included only if structured prompt interpretation can be reviewed and schema-validated; manual configuration remains sufficient for MVP acceptance. Scenario simulation and model benchmarking are not MVP blockers.

### MVP acceptance criteria

- A user can create and edit a hospital configuration with departments and beds, and invalid references are rejected with understandable feedback.
- A user can request a supported set of linked operational tables for a specified period and scale.
- Each completed run records its configuration snapshot, schema/generator version, seed if applicable, status, and timestamps.
- Generated rows pass documented required-field, key/reference, temporal, and configured capacity checks, or the run is marked with explicit findings.
- A user can inspect aggregate summaries and paginated sample rows without loading all rows into the client.
- A user can export generated CSV files and a manifest whose schema and run metadata match the saved run.
- Loading, empty, error, and success states are present; principal workflows are keyboard operable and responsive.
- Product copy consistently identifies outputs as synthetic and does not claim clinical suitability or real-world representativeness.

## Future roadmap

See [FEATURE_ROADMAP.md](FEATURE_ROADMAP.md) for phases, priorities, dependencies, and milestone gates.

## Assumptions and unresolved questions

- Initial deployment is a hosted SaaS for development/testing datasets, with no live clinical integration.
- The initial domain model focuses on operational events and capacity, not patient-level clinical data.
- Whether authentication is needed for the earliest private prototype or only hosted MVP remains a delivery decision; production SaaS requires it.
- Domain experts must confirm table grains, operational definitions (especially occupancy), capacity exceptions, waiting-list semantics, and plausible distributions.
- Data size limits, job duration targets, supported export formats, retention, pricing, and team/workspace model require validation.
- GenAI provider model/version, data retention settings, and whether prompts are sent off-platform require a privacy review.
- Quality metrics, thresholds, privacy testing, and intended claims require validation before being presented as guarantees.
