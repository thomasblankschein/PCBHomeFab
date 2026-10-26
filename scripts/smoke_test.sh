#!/usr/bin/env bash
# Smoke test of a running PCBHomeFab stack: create a job through the gateway, wait for it and check the .pm3 file.
# Usage: scripts/smoke_test.sh http://localhost
set -euo pipefail
base="${1:-http://localhost}"
data="$(dirname "$0")/../tests/data"

for _ in $(seq 1 60); do
    curl -fsS "$base/healthz" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS "$base/healthz"; echo
curl -fsS "$base/api/healthz"; echo
curl -fsS "$base/" | grep -q PCBHomeFab

response="$(curl -fsS -F "boards=@$data/basisplatine.zip" -F "boards=@$data/fuehlerknoten.zip" \
    -F counts=1 -F counts=3 -F exposure_s=60 "$base/api/v1/jobs")"
id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "job $id"

status=queued
for _ in $(seq 1 90); do
    status="$(curl -fsS "$base/api/v1/jobs/$id" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    [ "$status" = done ] || [ "$status" = failed ] && break
    sleep 1
done
echo "status $status"
[ "$status" = done ]

curl -fsS -o /tmp/pcbhomefab_smoke.pm3 "$base/api/v1/jobs/$id/files/exposure.pm3"
head -c 8 /tmp/pcbhomefab_smoke.pm3 | grep -q ANYCUBIC
curl -fsS "$base/jobs/$id" | grep -q job.js
echo "smoke test passed"
