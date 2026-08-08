# TASK-22 release verification evidence

**Evidence source branch:** `release-readiness`  
**Evidence source commit:** `6700825ed19ed715c4b43ddb613afcd15852cf1c`  
**Tested pull-request merge commit:** `582679a3d5f03c512509b9298e9ea60428e900dd`  
**Pull request:** #22  
**Verification CI:** run `31245909529`, run #109 — success  
**Release Evidence:** run `31245909530`, run #2 — success

This record contains only checks and measurements that were actually executed. The complete UCI source is intentionally not committed; the manual full-dataset profile was therefore **not run** as part of TASK-22, and no final UCI model ranking or weather-benefit result is claimed here.

## Verification summary

| Gate | Actual result |
|---|---|
| Locked backend synchronization | success; CPython 3.13.14, uv 0.12.2 |
| Ruff lint | success |
| Ruff format check | success |
| mypy | success |
| Backend unit tests | 154 passed, 1 deselected |
| PostgreSQL/TimescaleDB integration tests | 42 passed, 1 deselected |
| API-focused integration coverage within that integration suite | 22 tests passed |
| Mandatory ML guards | 15 passed, 184 deselected |
| Backend coverage run | 196 passed, 3 deselected; critical package coverage 87% |
| Alembic upgrade | success; head `c3d9a5f27410` |
| Alembic drift check | success; no new upgrade operations required |
| Runtime OpenAPI drift | success |
| Design/runtime OpenAPI assertions | success |
| Generated TypeScript SDK drift | success |
| Frontend component tests | 14 passed across 5 files |
| Frontend lint | success |
| Frontend typecheck | success |
| Frontend production build | success; Vite 7.3.6 transformed 838 modules |
| Playwright Chromium E2E | 1 passed in 7.2 s |
| Docker image build | success |
| Clean-volume six-service Compose smoke | success |
| Infrastructure hardening contract | success |
| Dependency audit | success; frontend install reported 0 vulnerabilities |
| Secret/private-file scan | success |
| Container vulnerability scan | success for backend, web and edge images |
| `git diff --check` / workflow YAML parse | success |
| Repository-wide `scripts/verify.ps1` | success |
| Documentation link/Mermaid structure verification | success in Release Evidence run |
| Performance regression marker | 1 passed, 1 skipped because the TimescaleDB-only performance case requires `TEST_DATABASE_URL`; 197 deselected |

The integration job runs against the pinned TimescaleDB/PostgreSQL service and includes API, migrations, repositories, artifacts, queue/worker, model-bundle and forecast/export behavior. The coverage job ran the combined eligible backend suite and is separate from the mandatory leakage-guard count above.

## Deterministic performance profile

Release Evidence used deterministic synthetic fixtures on this GitHub-hosted runner profile:

- CPU: AMD EPYC 9V74 80-Core Processor;
- logical CPUs exposed: 4;
- memory: 16,766,423,040 bytes;
- platform: Linux 6.17.0-1020-azure x86_64, glibc 2.39;
- Python: 3.13.14;
- random seed: 42;
- ML benchmark parallelism: `n_jobs=1`.

Measured values from `release-benchmark.json`:

| Operation | Measured result |
|---|---:|
| Streaming parse, 50,000 UCI-shaped rows | median 772.274191 ms; p95 772.623827 ms; 64,743.84 rows/s |
| Quality evaluation, 10,000 minute rows | median 49.002625 ms; p95 174.332200 ms |
| Hourly transformation, 24 h minute rows | median 6.857282 ms; p95 6.924340 ms |
| Bounded analytics bucket selection | median 0.001562 ms; p95 0.001673 ms over 1,000 repetitions |
| FastAPI liveness request through ASGI TestClient | median 1.355032 ms; p95 1.523044 ms over 100 repetitions |
| Ridge direct-24 training | median 0.016361 s across 3 measured fits after warmup |
| Ridge direct-24 prediction | median 2.961151 ms; p95 3.357788 ms across 30 predictions |
| Serialized Ridge direct-24 artifact | 2,183 bytes |

The ML timing fixture contains 96 rows, 5 features and 24 horizons. These values are engineering performance evidence, not final scientific results on the UCI dataset.

## Security and deployment verification

The PR verification successfully executed dependency audit, Gitleaks/private-path checks, Trivy HIGH/CRITICAL fixed-vulnerability scans, infrastructure contract validation, production image builds and clean-volume Compose smoke. The final security review is in `docs/evidence/security-review.md`.

No authentication/TLS gateway is implemented in the coursework baseline; direct untrusted-Internet exposure remains outside the supported deployment boundary.

## Known non-blocking warnings and limits

- `npm ci` reports that `esbuild@0.28.1` has a postinstall script not yet covered by npm `allowScripts`; install/audit still completed with 0 vulnerabilities.
- Vite reports one minified JavaScript chunk at 1,582.44 kB (513.94 kB gzip), above the 500 kB warning threshold. The build completed successfully.
- GitHub's `actions/upload-artifact@v4` emitted hosted-runner Node/deprecation warnings unrelated to product runtime.
- The full UCI profile was not run because the source dataset is intentionally external to Git.
- W1 weather mode remains unsupported without a real weather source; no weather-benefit result is asserted.
