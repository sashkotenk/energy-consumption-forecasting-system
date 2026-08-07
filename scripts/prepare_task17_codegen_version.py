"""One-shot TASK-17 patch selecting the audited safe code-generator release."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
package_path = root / "frontend/package.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
package["devDependencies"]["@hey-api/openapi-ts"] = "0.97.0"
package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8", newline="\n")

log_path = root / "docs/implementation-log.md"
log = log_path.read_text(encoding="utf-8")
log = log.replace(
    "`@hey-api/openapi-ts` 0.99.0 is pinned exactly as a frontend development dependency",
    "`@hey-api/openapi-ts` 0.97.0 is pinned exactly as a frontend development dependency",
)
log_path.write_text(log, encoding="utf-8", newline="\n")
print("Pinned @hey-api/openapi-ts 0.97.0 after npm audit rejected 0.99.0")
