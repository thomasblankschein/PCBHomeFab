"""Login for the tests against a running stack: every call of the API needs the access token of an account.

Give an account of the stack in the environment (create one with ``scripts/create_user.sh``):
``PCBHOMEFAB_USER`` and ``PCBHOMEFAB_PASSWORD``, or a ready token in ``PCBHOMEFAB_TOKEN``.
"""

from __future__ import annotations

import os

import httpx
import pytest

TOKEN_PATH = "/auth/realms/pcbhomefab/protocol/openid-connect/token"


def auth_headers(base: str) -> dict[str, str]:
    """The ``Authorization`` header for the stack at ``base``; skips the test when no account is given."""
    token = os.environ.get("PCBHOMEFAB_TOKEN")
    if not token:
        user, password = os.environ.get("PCBHOMEFAB_USER"), os.environ.get("PCBHOMEFAB_PASSWORD")
        if not user or not password:
            pytest.skip("set PCBHOMEFAB_USER and PCBHOMEFAB_PASSWORD (an account of the stack) to run the e2e tests")
        response = httpx.post(
            f"{base}{TOKEN_PATH}",
            data={"client_id": "pcbhomefab-cli", "grant_type": "password", "username": user, "password": password},
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
