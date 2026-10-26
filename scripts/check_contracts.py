"""Validate the contracts: JSON schemas, OpenAPI files and the examples against their schemas.

Usage: python scripts/check_contracts.py   (needs PyYAML and jsonschema)
"""

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent / "contracts"
EXAMPLES = {
    "board-basisplatine.json": "board",
    "board-fuehlerknoten.json": "board",
    "layout-request.json": "layout-request",
    "layout.json": "layout",
    "exposure-settings.json": "exposure-settings",
    "mill-settings.json": "mill-settings",
}


def main() -> int:
    errors: list[str] = []
    schemas = {p.stem.removesuffix(".schema"): json.loads(p.read_text()) for p in (ROOT / "schemas").glob("*.json")}
    registry = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    for name, schema in schemas.items():
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            errors.append(f"schemas/{name}: {exc}")
    for path in sorted(ROOT.glob("*.openapi.yaml")):
        spec = yaml.safe_load(path.read_text())
        if spec.get("openapi") != "3.1.0" or not spec.get("paths"):
            errors.append(f"{path.name}: not an OpenAPI 3.1 document with paths")
        for route, operations in spec["paths"].items():
            if not route.startswith(("/v1/", "/healthz")):
                errors.append(f"{path.name}: path {route} is not versioned")
            for method, operation in operations.items():
                if "operationId" not in operation:
                    errors.append(f"{path.name}: {method} {route} has no operationId")
    for filename, schema_name in EXAMPLES.items():
        schema = schemas[schema_name]
        example = json.loads((ROOT / "examples" / filename).read_text())
        for problem in Draft202012Validator(schema, registry=registry).iter_errors(example):
            errors.append(f"examples/{filename}: {problem.message}")
    for line in errors:
        print(line)
    print("contracts ok" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
