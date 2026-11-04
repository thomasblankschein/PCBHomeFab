#!/usr/bin/env bash
# Creates an account in the login (Keycloak) of a running PCBHomeFab stack.
# Usage, on the Docker host in the folder of the repository:
#   scripts/create_user.sh <username> [email] [first name] [last name]
# The script asks for the password of the new account (at least 12 characters), or takes it from PCBHOMEFAB_NEW_PASSWORD.
# It runs the admin tool of Keycloak (kcadm.sh) inside the keycloak container, so no administrator password goes over the
# network and the console does not have to be reachable. It logs in with the administrator of the .env file; after a change
# of that password give the new one in KEYCLOAK_ADMIN_PASSWORD (and KEYCLOAK_ADMIN_USER for another name).
# Keycloak wants an email address and a first and a last name (without them the account counts as not fully set up and
# cannot log in); they default to <username>@example.invalid, the username and a dash. The same can be done by hand in the
# Keycloak console at <address>/auth/admin (realm pcbhomefab, Users).
# COMPOSE overrides the compose command, e.g. COMPOSE="docker compose -p pcbhomefab-test".
set -euo pipefail
user="${1:?username}"
email="${2:-$user@example.invalid}"
first="${3:-$user}"
last="${4:--}"
compose="${COMPOSE:-docker compose}"

password="${PCBHOMEFAB_NEW_PASSWORD:-}"
if [ -z "$password" ]; then
    read -rsp "Password for $user: " password; echo
    read -rsp "Password again: " again; echo
    [ "$password" = "$again" ] || { echo "the passwords differ" >&2; exit 1; }
fi

body="$(python3 -c '
import json, sys
user, password, email, first, last = sys.argv[1:6]
print(json.dumps({"username": user, "email": email, "firstName": first, "lastName": last,
                  "enabled": True, "emailVerified": True,
                  "credentials": [{"type": "password", "value": password, "temporary": False}]}))
' "$user" "$password" "$email" "$first" "$last")"

# The account goes in on stdin, so the password shows up in no command line. Without KEYCLOAK_ADMIN_* on this host the
# administrator of the first start is taken from the environment of the container.
# shellcheck disable=SC2016  # the variables are expanded inside the container
if ! output="$(printf '%s' "$body" | $compose exec -T -e KEYCLOAK_ADMIN_USER -e KEYCLOAK_ADMIN_PASSWORD keycloak bash -c '
    set -e
    kcadm=/opt/keycloak/bin/kcadm.sh
    config="$(mktemp)"
    trap "rm -f $config" EXIT
    export KC_CLI_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-$KC_BOOTSTRAP_ADMIN_PASSWORD}"  # not on the command line
    $kcadm config credentials --config "$config" --server http://localhost:8080/auth --realm master \
        --user "${KEYCLOAK_ADMIN_USER:-$KC_BOOTSTRAP_ADMIN_USERNAME}" >/dev/null
    $kcadm create users --config "$config" -r pcbhomefab -f -
' 2>&1)"; then
    echo "$output" >&2
    echo "account $user not created (does it exist already? is the password long enough?)" >&2
    exit 1
fi
echo "account $user created"
