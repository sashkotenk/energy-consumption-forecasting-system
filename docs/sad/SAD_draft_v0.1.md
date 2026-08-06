# EnergyForecast
## Software Architecture Document (SAD)

**Document status:** Draft v0.1  
**Date:** 2026-08-06  
**Content owner:** Oleksandr Bondarchuk  
**System:** EnergyForecast  
**Course:** Software Engineering bachelor course project  
**Important:** This document describes the planned baseline. It must be revised after implementation so that every statement reflects the actual system.

---

# 1. Introduction

## 1.1 Purpose

This Software Architecture Document describes the architecturally significant decisions, elements, interfaces, data flows, deployment model, constraints, and quality attributes of EnergyForecast.

EnergyForecast is a client-server web application for importing energy-consumption time series, assessing data quality, creating hourly datasets, analyzing consumption patterns, training and comparing forecasting methods, generating a 24-hour forecast, and exporting results.

The SAD is intended for:

- the student implementing and maintaining the system;
- the course supervisor and assessment committee;
- a tester reviewing functional and ML correctness;
- a future developer extending algorithms or storage adapters.

## 1.2 Problem Definition

Historical energy data is frequently stored in raw CSV-like files with missing values, duplicates, irregular timestamps, inconsistent units, and insufficient experiment traceability. A forecasting result alone is not enough: the system must preserve the source, document transformations, prevent temporal leakage, evaluate models chronologically, and make results available through a usable interface.

## 1.3 Objectives

The architecture shall support:

1. immutable source-file preservation;
2. chunked ingestion of a multi-million-row dataset;
3. explicit data-quality and transformation policies;
4. reproducible ML experiments;
5. Seasonal Naive, Ridge, Random Forest, and Histogram Gradient Boosting;
6. direct 24-step forecasting;
7. REST/OpenAPI access;
8. a Ukrainian React user interface;
9. local deployment with Docker Compose;
10. automated unit, integration, component, and end-to-end testing.

## 1.4 Scope

### Included

- UCI and generic CSV import;
- quality assessment;
- short-gap interpolation and hourly aggregation;
- PostgreSQL/TimescaleDB persistence;
- analysis views and charts;
- feature engineering;
- chronological model evaluation;
- model comparison;
- 24-hour forecast;
- exports;
- Docker Compose and CI.

### Excluded

- user registration and role management;
- public multi-tenant SaaS;
- smart-meter connectivity;
- device control;
- tariff or billing calculations;
- online learning;
- microservices and Kubernetes;
- mandatory neural networks;
- mandatory live weather forecast integration.

## 1.5 Glossary

| Term | Definition |
|---|---|
| Dataset | A logical user-visible collection of energy measurements. |
| Dataset version | An immutable source or derived representation with a manifest. |
| Forecast origin | The end of the last fully available hour used to create a forecast. |
| Job | A persisted long-running background command. |
| W0 | Experiment using consumption and calendar features without weather. |
| W1 | Idealized experiment using future reanalysis weather; not a fully operational weather forecast scenario. |
| Model run | One algorithm and hyperparameter configuration inside an experiment. |
| Artifact | A file such as raw CSV, model bundle, metrics export, or chart. |
| SAD | Software Architecture Document. |

---

# 2. Stakeholders and Concerns

| Stakeholder | Main concerns | Architecture views |
|---|---|---|
| Energy analyst | usability, data quality, understandable results, export | context, container, UI, dynamic |
| Student developer | modularity, implementation order, debugging | container, component, code |
| Supervisor/committee | justified decisions, own contribution, reproducibility | summary views, decisions |
| Tester | deterministic behavior, leakage protection, contracts | component, data, testing |
| Operator | startup, health, persistence, backup | deployment |

---

# 3. Functional Requirements

- **FR-01:** Import the fixed UCI format and a mapped generic CSV.
- **FR-02:** Detect missing values, duplicates, temporal gaps, invalid values, and anomalies.
- **FR-03:** Apply a recorded transformation policy and aggregate to hourly kWh.
- **FR-04:** Provide descriptive statistics and time-based visual analysis.
- **FR-05:** Run reproducible experiments with the required algorithms.
- **FR-06:** Compare models on identical chronological evaluation rows.
- **FR-07:** Generate and persist a 24-hour forecast.
- **FR-08:** Export forecasts, metrics, manifests, and charts.
- **FR-09:** Preserve dataset, experiment, model, and forecast history.
- **FR-10:** Expose the main functionality through REST API.

---

# 4. Quality Attributes

## 4.1 Reproducibility

Every completed experiment records dataset checksum/version, feature schema, split definition, parameters, random seed, software commit, dependency versions, metrics, and artifact checksum.

## 4.2 Modularity

HTTP, application orchestration, domain policies, persistence, file storage, and ML implementation are separated. Algorithm changes do not require controller or UI rewrites.

## 4.3 Reliability

Long work is stored as a database job and executed by a separate worker process. An interrupted browser or API connection does not stop training.

## 4.4 Security

Uploads use an extension allowlist, generated filenames, size limits, content validation, storage outside the web root, and controlled downloads. Untrusted joblib/pickle import is not supported.

## 4.5 Testability

Feature construction, temporal splitting, metrics, state transitions, and selection rules are pure or dependency-injected components with deterministic tests.

## 4.6 Portability

The baseline is a pinned Docker Compose deployment and has no mandatory cloud dependency.

---

# 5. Architecture Overview

## 5.1 Style

EnergyForecast is a modular monolith. The backend is one codebase deployed as two processes:

- FastAPI API;
- background worker.

The system is not a microservice architecture. The processes share domain modules, database schema, release lifecycle, and source repository.

## 5.2 Containers

| Container | Technology | Responsibility |
|---|---|---|
| Reverse proxy | Nginx | single entry point, upload limits, proxy/static delivery |
| Web application | React/TypeScript/Vite | forms, navigation, charts, job polling |
| API | FastAPI/Pydantic | REST commands and queries, OpenAPI |
| Worker | Python | ingestion, transformation, ML, export |
| Database | PostgreSQL/TimescaleDB | relational metadata, job state, time series |
| Artifact store | local filesystem adapter | raw files, models, exports |

## 5.3 Context

The analyst interacts with EnergyForecast through a browser. The system optionally obtains ERA5-Land data through a weather API. The UCI file is a control source but is not a permanent runtime dependency.

## 5.4 Runtime Flow

A long command is handled as follows:

1. API validates the request.
2. API persists the domain resource and a queued job.
3. API returns `202 Accepted`.
4. Worker claims the job using PostgreSQL row locking.
5. Worker reports heartbeat and progress.
6. Worker persists results and terminal state.
7. React polls the job and invalidates affected queries.

---

# 6. Components and Interfaces

## 6.1 Backend Modules

- Dataset Catalog
- Ingestion
- Data Quality
- Transformations
- Analytics Query
- Experiment Management
- Feature Pipeline
- Model Registry
- Forecasting
- Weather Adapter
- Jobs
- Artifacts

## 6.2 Dependency Rule

API routers call application use cases. Use cases depend on domain ports. SQLAlchemy, filesystem, HTTP clients, Pandas, and scikit-learn are infrastructure implementations.

## 6.3 Public REST Interface

Base path: `/api/v1`.

Main resources:

- `/datasets`
- `/dataset-imports`
- `/dataset-versions`
- `/experiments`
- `/algorithms`
- `/forecasts`
- `/jobs`
- `/health`

Long operations return a job resource. Errors use Problem Details. The FastAPI-generated OpenAPI document becomes the source of truth and is used to generate the TypeScript client.

## 6.4 Internal Worker Interface

The API and worker communicate only through persisted job and domain records. There is no internal HTTP service.

The worker supports:

- claim;
- heartbeat;
- cooperative cancellation;
- retry;
- stale recovery;
- terminal success/failure.

---

# 7. Data Architecture

## 7.1 Relational Metadata

Regular PostgreSQL tables store:

- datasets and immutable versions;
- artifacts;
- jobs;
- quality issues;
- transformation runs;
- experiments and model runs;
- folds and metrics;
- forecasts and points.

## 7.2 Time-Series Tables

TimescaleDB hypertables store:

- raw normalized measurements;
- hourly observations;
- weather observations.

Every unique key on a hypertable includes its time partitioning column.

## 7.3 Artifact Storage

Large binaries are stored outside PostgreSQL. The database stores generated key, media type, size, SHA-256, kind, and creation time. Storage is accessed only through `ArtifactStore`.

## 7.4 Derived Hourly Data

Hourly observations are materialized by the application pipeline rather than a basic continuous aggregate because the result depends on interpolation, duplicate handling, coverage, quality status, and a versioned policy.

---

# 8. Data and ML Pipeline

```text
immutable source
→ chunked parser
→ normalized raw rows
→ quality engine
→ transformation policy
→ hourly observations
→ feature builder
→ leakage guard
→ expanding chronological validation
→ algorithm tuning
→ selection rule
→ final fit and one-time final test
→ model bundle
→ 24-hour forecast
```

The model bundle includes the model, feature schema, algorithm, horizon, training dataset version, commit, seed, library versions, and checksum.

W0 does not use weather. W1 uses future reanalysis weather as an explicitly idealized research scenario.

---

# 9. Architectural Decisions

1. **Modular monolith instead of microservices.**
2. **Separate API and worker processes.**
3. **PostgreSQL-backed job queue instead of Redis/Celery in the baseline.**
4. **TimescaleDB for temporal facts and PostgreSQL tables for metadata.**
5. **Application-materialized hourly data instead of continuous aggregates for cleaning.**
6. **Filesystem artifact adapter instead of large database BLOBs.**
7. **OpenAPI-generated frontend client.**
8. **REST polling instead of WebSocket/SSE.**
9. **No built-in authentication in the course scope.**
10. **Weather is optional.**
11. **Direct 24-horizon forecasting behind one model interface.**
12. **No untrusted model deserialization.**

---

# 10. Deployment

Docker Compose services:

```text
db
migrate
api
worker
web
nginx
```

The database and artifact store use persistent volumes. Migration is a one-shot service. API and worker start only after the database is healthy and migrations succeed.

Production exposes only Nginx. Database ports remain internal. Backups include both the database and artifact volume.

---

# 11. Testing

## 11.1 Backend

- unit tests for parsing, quality, aggregation, features, splits, metrics, selection, and state machines;
- integration tests against a real containerized PostgreSQL/TimescaleDB-compatible database;
- API and OpenAPI contract tests;
- migration tests;
- artifact and weather-adapter tests;
- ML reproducibility and leakage tests.

## 11.2 Frontend

- Vitest for logic;
- React Testing Library for forms and components;
- Playwright for the primary end-to-end workflow.

## 11.3 Mandatory ML Guards

The suite verifies that rolling features exclude current/future values, preprocessing is fitted only on training data, train and validation targets do not overlap, W0/W1 use identical evaluation rows, final test is not exposed to tuning, and serialized models reproduce predictions.

---

# 12. Risks and Technical Debt

| Risk | Mitigation |
|---|---|
| PostgreSQL queue is not a high-scale broker | baseline one worker; clear adapter boundary |
| Local artifact volume can be lost | coordinated backup and checksum manifest |
| Timescale version differences | pinned image and migration tests |
| joblib is unsafe for untrusted data | only internally created verified artifacts |
| weather coordinates/timezone are approximate | W1 separated and documented |
| design may diverge from code | SAD update required before submission |
| large charts can overload browser | server aggregation and `max_points` |

---

# 13. Requirements Coverage

The architecture maps import to Ingestion/Artifacts, quality to Quality Engine, hourly conversion to Transformations, visualization to Analytics Query and React widgets, training to Experiment/Worker/Model Registry, forecasts to Forecast Service, and reproducibility to immutable versions, manifests, checksums, and tests.

---

# 14. Referenced Materials

- ISO/IEC/IEEE 42010:2022.
- Clements et al., *Documenting Software Architectures: Views and Beyond*.
- Bass, Clements, Kazman, *Software Architecture in Practice*.
- Simon Brown, C4 Model.
- OpenAPI Specification 3.1.1.
- FastAPI official documentation.
- PostgreSQL official documentation.
- TimescaleDB official documentation.
- OWASP File Upload Cheat Sheet.
- React, TanStack Query, Docker Compose, Testcontainers, pytest, Vitest and Playwright official documentation.
- Scientific forecasting sources listed in the EnergyForecast experimental protocol.

---

# 15. Revision Checklist for Final SAD

Before submission:

- replace planned statements with actual implementation facts;
- insert exported diagrams and figure numbers;
- record exact image/dependency versions;
- record implemented endpoints and tables;
- document deviations through ADRs;
- add actual test and performance results;
- remove unimplemented components;
- verify every requirement has implementation and test evidence.
