"""One-shot TASK-17 patch for Problem Details OpenAPI media schemas."""

from pathlib import Path

path = Path(__file__).resolve().parents[1] / "backend/src/energy_forecast/api.py"
text = path.read_text(encoding="utf-8")
old = '''        readiness_response = schema["paths"]["/health/ready"]["get"]["responses"]["503"]
        readiness_response["content"] = {
            PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}
        }
'''
new = '''        problem_schema = {"schema": {"$ref": "#/components/schemas/Problem"}}
        for path_item in schema["paths"].values():
            if not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                responses = operation.get("responses")
                if not isinstance(responses, dict):
                    continue
                for response in responses.values():
                    if not isinstance(response, dict):
                        continue
                    content = response.get("content")
                    if not isinstance(content, dict) or PROBLEM_MEDIA_TYPE not in content:
                        continue
                    content[PROBLEM_MEDIA_TYPE] = problem_schema
                    application_json = content.get("application/json")
                    if (
                        isinstance(application_json, dict)
                        and application_json.get("schema", {}).get("$ref")
                        == "#/components/schemas/Problem"
                    ):
                        content.pop("application/json", None)
'''
if new not in text:
    if old not in text:
        raise SystemExit("Expected readiness-only Problem Details OpenAPI patch was not found")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print("Problem Details OpenAPI schemas normalized")
