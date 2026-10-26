"""Check the architecture rules of ADR-001 (docs/architecture.md). Exit code 1 when a rule is broken.

- No service imports or refers to the code of another service.
- No Dockerfile copies files from outside its own folder.
- Only the gateway publishes ports, only the gateway is on the outside network.
- No volume is used by more than one service, no bind mounts.

Usage: python scripts/check_boundaries.py   (needs PyYAML)
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ROOT / "services"
PYTHON_SERVICES = ["ingest", "panel", "exposure", "mill", "jobs"]


def check_code() -> list[str]:
    problems: list[str] = []
    names = [p.name for p in SERVICES.iterdir() if p.is_dir()]
    for service in names:
        others = [n for n in names if n != service]
        import_pattern = re.compile(rf"^\s*(?:from|import)\s+(?:{'|'.join(PYTHON_SERVICES)})\b", re.M)
        for path in (SERVICES / service).rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".toml", ".yaml", ".yml", ""} or ".venv" in path.parts:
                continue
            if "__pycache__" in path.parts or path.name.endswith((".zip", ".png", ".bin")):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            relative = path.relative_to(ROOT).as_posix()
            if path.suffix == ".py":
                for match in import_pattern.finditer(text):
                    imported = match.group(0).split()[-1]
                    if imported != service:
                        problems.append(f"{relative}: imports the code of service '{imported}'")
            for other in others:
                if re.search(rf"services/{other}\b", text) and path.name != "conftest.py":
                    problems.append(f"{relative}: refers to the folder of service '{other}'")
    for dockerfile in SERVICES.glob("*/Dockerfile"):
        for line in dockerfile.read_text().splitlines():
            if line.strip().upper().startswith(("COPY", "ADD")) and ".." in line:
                problems.append(f"{dockerfile.relative_to(ROOT).as_posix()}: copies from outside its folder: {line}")
    return problems


def check_compose() -> list[str]:
    problems: list[str] = []
    compose = yaml.safe_load((ROOT / "docker-compose.yaml").read_text())
    users: dict[str, list[str]] = {}
    for name, service in compose["services"].items():
        if name != "gateway" and service.get("ports"):
            problems.append(f"docker-compose.yaml: service '{name}' publishes ports, only the gateway may")
        if name != "gateway" and "edge" in (service.get("networks") or []):
            problems.append(f"docker-compose.yaml: service '{name}' is on the outside network")
        for volume in service.get("volumes") or []:
            source = volume.split(":")[0]
            if source.startswith((".", "/", "~")):
                problems.append(f"docker-compose.yaml: service '{name}' has a bind mount ({volume})")
            else:
                users.setdefault(source, []).append(name)
    for volume, names in users.items():
        if len(names) > 1:
            problems.append(f"docker-compose.yaml: volume '{volume}' is shared by {', '.join(names)}")
    if not compose.get("networks", {}).get("internal", {}).get("internal"):
        problems.append("docker-compose.yaml: network 'internal' must be internal")
    return problems


def main() -> int:
    problems = check_code() + check_compose()
    for line in problems:
        print(line)
    print("boundaries ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
