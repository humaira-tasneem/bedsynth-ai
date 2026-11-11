# BedSynth AI Feature Roadmap

**Status:** Proposed sequencing, subject to discovery and review. No phase is presented as completed.

## Prioritization

- **P0:** Needed for a coherent, reviewable MVP workflow.
- **P1:** Improves usability, team use, or robustness after MVP foundations.
- **P2:** Advanced capability with domain or workload dependencies.

## Phases and milestones

| Phase | Priority | Scope and milestone | Dependencies / exit gate |
|---|---|---|---|
| 0. Product and domain definition | P0 | Agree event grains, occupancy calculation, constraints, supported output tables, synthetic-data claims, and MVP limits. | Domain review; privacy and deployment assumptions recorded. Gate: testable schemas and acceptance examples approved. |
| 1. Foundation | P0 | Establish repository structure, API contracts, database migrations, design tokens, authentication/tenant boundary for hosted MVP, and CI quality gates. | Phase 0; hosting and identity choice. Gate: a user can create/read a private hospital configuration through the UI/API. |
| 2. Hospital configuration | P0 | Hospital, department, bed inventory and basic constraints with validation and edit flows. | Foundation schemas. Gate: invalid references and unsupported configurations are rejected clearly. |
| 3. Generation and integrity | P0 | Versioned run configuration, bounded generation job, linked admissions/discharges/transfers and occupancy output, status/history, seed/provenance capture. | Domain schema, generation methods, output-storage choice, job execution approach. Gate: documented invariants pass or findings block/label run. |
| 4. Inspect, evaluate, export | P0 | Quality results, summary analytics, paginated preview, CSV plus manifest, responsive and accessible states. | Dataset storage and schema; evaluation definitions; chart aggregation semantics. Gate: full MVP journey passes agreed acceptance scenarios. |
| 5. Prompt assistant | P1 | Gemini structured prompt interpretation into a reviewable configuration proposal with manual fallback. | Privacy/provider review, strict schemas, validation and rate limits. Gate: malformed/unsupported output is safely rejected and user approval is required before generation. |
| 6. Team and operational maturity | P1 | Workspace membership/roles, audit/retention controls, stronger observability, job recovery and refined scaling. | User demand, threat model, hosting and support model. Gate: access and deletion behavior reviewed. |
| 7. Scenarios and benchmarking | P2 | Baseline/scenario comparison, controlled parameter changes, documented model benchmark workflows. | Stable domain semantics, comparable generation, benchmark definitions, evaluation and claim review. Gate: metrics include assumptions and limitations. |
| 8. Scale and integrations | P2 | Larger exports, optional formats, API integrations, and alternative generation methods based on measured demand. | Workload evidence, storage/compute costs, supported integrations and governance. Gate: load and recovery objectives defined and reviewed. |

## MVP versus advanced

**MVP candidate:** one private user/workspace; virtual hospital configuration; departments/beds; bounded generation of linked operational tables; deterministic seed capture where supported; structural and configured operational validation; basic summaries; paginated preview; CSV and manifest; run history; clear synthetic labeling; responsive light/dark UI.

**Advanced:** multi-user roles, rich scenario simulation, comparison dashboards, extended privacy/statistical evaluation, additional generator approaches, large-scale export, model benchmarking, and external integrations. GenAI assistant is P1 in this sequencing because the core workflow can be validated manually first; product may move it earlier if the privacy and structured-output gates are met.

## Cross-phase dependencies

- The definition of occupancy, bed availability, and transfer events is a prerequisite to trustworthy generation and charts.
- Row storage and export strategy depend on expected dataset volume, preview query patterns, and retention requirements.
- The background job approach depends on generation duration, hosting capabilities, retry semantics, and concurrency needs.
- Gemini integration depends on data-flow disclosure, provider configuration, schema validation, and abuse/cost controls.
- Benchmarking depends on an agreed evaluation protocol and must not imply real-world performance from synthetic-only tests.
- Accessibility and responsive design are acceptance criteria throughout, rather than a final phase.

## Planning notes

No dates, team size, costs, or delivery durations are assigned because capacity and deployment constraints were not provided. Milestones are capability gates, not delivery commitments.
