#!/usr/bin/env bash
# Smoke test of a running PCBHomeFab stack: create a job through the gateway, wait for it and check the .pm3 file.
# Usage: PCBHOMEFAB_USER=... PCBHOMEFAB_PASSWORD=... scripts/smoke_test.sh http://localhost
# The jobs need a login: give an account of the stack (create one with scripts/create_user.sh), or a ready token in
# PCBHOMEFAB_TOKEN.
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

# without a login the API is closed
[ "$(curl -s -o /dev/null -w '%{http_code}' "$base/api/v1/jobs")" = 401 ]

token="${PCBHOMEFAB_TOKEN:-}"
if [ -z "$token" ]; then
    : "${PCBHOMEFAB_USER:?set PCBHOMEFAB_USER and PCBHOMEFAB_PASSWORD, or PCBHOMEFAB_TOKEN}"
    : "${PCBHOMEFAB_PASSWORD:?set PCBHOMEFAB_PASSWORD}"
    token="$(curl -fsS -d client_id=pcbhomefab-cli -d grant_type=password --data-urlencode "username=$PCBHOMEFAB_USER" \
        --data-urlencode "password=$PCBHOMEFAB_PASSWORD" "$base/auth/realms/pcbhomefab/protocol/openid-connect/token" |
        python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
fi
auth="Authorization: Bearer $token"

response="$(curl -fsS -H "$auth" -F "boards=@$data/basisplatine.zip" -F "boards=@$data/fuehlerknoten.zip" \
    -F counts=1 -F counts=3 -F panel=160x100 -F margin_mm=5 -F exposure_s=60 "$base/api/v1/jobs")"
id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "job $id"

status=queued
for _ in $(seq 1 90); do
    status="$(curl -fsS -H "$auth" "$base/api/v1/jobs/$id" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    [ "$status" = done ] || [ "$status" = failed ] && break
    sleep 1
done
echo "status $status"
[ "$status" = done ]

curl -fsS -H "$auth" -o /tmp/pcbhomefab_smoke.pm3 "$base/api/v1/jobs/$id/files/exposure.pm3"
head -c 8 /tmp/pcbhomefab_smoke.pm3 | grep -q ANYCUBIC
curl -fsS "$base/jobs/$id" | grep -q job.js
curl -fsS -H "$auth" "$base/api/v1/jobs" | grep -q "$id"
curl -fsS -H "$auth" -X DELETE "$base/api/v1/jobs/$id"
echo "smoke test passed"
