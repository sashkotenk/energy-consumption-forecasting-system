"""One-shot TASK-17 patch selecting the audited code-generator release."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
package_path = root / "frontend/package.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
package["scripts"]["api:generate"] = "orval --clean --fail-on-warnings"
package["scripts"]["api:check"] = (
    "npm run api:generate && git diff --exit-code -- ../docs/api/openapi.json src/generated/api"
)
package["devDependencies"].pop("@hey-api/openapi-ts", None)
package["devDependencies"]["orval"] = "8.23.0"
package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8", newline="\n")

log_path = root / "docs/implementation-log.md"
log = log_path.read_text(encoding="utf-8")
log = log.replace(
    "- `@hey-api/openapi-ts` 0.99.0 is pinned exactly as a frontend development dependency for\n  deterministic OpenAPI-to-TypeScript generation. No backend runtime dependency changed.",
    "- `orval` 8.23.0 is pinned exactly as a frontend development dependency for deterministic\n  OpenAPI-to-TypeScript fetch-client generation. Hey API 0.99.0 and 0.97.0 were evaluated but\n  rejected because npm audit reported high and moderate vulnerabilities respectively. No backend\n  runtime dependency changed.",
)
log_path.write_text(log, encoding="utf-8", newline="\n")
print("Pinned Orval 8.23.0 after audited Hey API releases were rejected")
