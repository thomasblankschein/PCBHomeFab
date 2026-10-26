"""Contract helpers (copied into each service's tests, no shared code): validate bodies against ``contracts/``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
SERVICE = "mill"


def _registry() -> Registry:
    schemas = [json.loads(p.read_text()) for p in (CONTRACTS / "schemas").glob("*.json")]
    return Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas])


def validate(schema_name: str, instance: Any) -> None:
    """Raise if ``instance`` does not match ``contracts/schemas/<schema_name>.schema.json``."""
    schema = json.loads((CONTRACTS / "schemas" / f"{schema_name}.schema.json").read_text())
    Draft202012Validator(schema, registry=_registry()).validate(instance)


def contract_operations() -> set[tuple[str, str]]:
    """``(METHOD, path)`` of every operation in the OpenAPI file of this service."""
    spec = yaml.safe_load((CONTRACTS / f"{SERVICE}.openapi.yaml").read_text())
    return {(method.upper(), path) for path, operations in spec["paths"].items() for method in operations}


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return Path(__file__).parent / "data"
