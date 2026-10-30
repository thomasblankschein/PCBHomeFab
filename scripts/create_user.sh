#!/usr/bin/env bash
# Creates an account in the login (Keycloak) of a running PCBHomeFab stack.
# Usage: KEYCLOAK_ADMIN_PASSWORD=... scripts/create_user.sh <address> <username> <password> [email] [first name] [last name]
#   <address>  what the users type in the browser, e.g. http://localhost or https://pcbhomefab.example.org
# The administrator is the one of the .env file (KEYCLOAK_ADMIN_USER, default admin). The password needs at least 10
# characters. Keycloak wants a first and a last name (without them the account counts as not fully set up and cannot
# log in); they default to the username and a dash. The same can be done by hand in the Keycloak console at <address>/auth/admin (realm pcbhomefab, Users).
set -euo pipefail
base="${1:?address of the stack, e.g. http://localhost}"
user="${2:?username}"
password="${3:?password (at least 10 characters)}"
email="${4:-$user@example.invalid}"
first="${5:-$user}"
last="${6:--}"
admin_user="${KEYCLOAK_ADMIN_USER:-admin}"
admin_password="${KEYCLOAK_ADMIN_PASSWORD:?set KEYCLOAK_ADMIN_PASSWORD}"

token="$(curl -fsS -d client_id=admin-cli -d grant_type=password --data-urlencode "username=$admin_user" \
    --data-urlencode "password=$admin_password" "$base/auth/realms/master/protocol/openid-connect/token" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

body="$(python3 -c '
import json, sys
user, password, email, first, last = sys.argv[1:6]
print(json.dumps({"username": user, "email": email, "firstName": first, "lastName": last,
                  "enabled": True, "emailVerified": True,
                  "credentials": [{"type": "password", "value": password, "temporary": False}]}))
' "$user" "$password" "$email" "$first" "$last")"

status="$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$body" "$base/auth/admin/realms/pcbhomefab/users")"
case "$status" in
    201) echo "account $user created" ;;
    409) echo "account $user exists already" >&2; exit 1 ;;
    *) echo "Keycloak answered $status (is the password long enough?)" >&2; exit 1 ;;
esac
