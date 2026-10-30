"""The check of real access tokens: signature, issuer, expiry and client are verified with a locally made key pair."""

import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from jobs.auth import OidcVerifier, authenticate, bearer_token
from jobs.common import Problem

ISSUER = "https://pcb.example/auth/realms/pcbhomefab"


@pytest.fixture(scope="module")
def key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _verifier(key: Any) -> OidcVerifier:
    verifier = OidcVerifier(ISSUER, "http://keycloak:8080/certs", ("pcbhomefab-web",))
    verifier._keys = SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=key.public_key()))  # type: ignore[assignment]
    return verifier


def _token(key: Any, **changes: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "user-1",
        "azp": "pcbhomefab-web",
        "exp": time.time() + 300,
        "preferred_username": "thomas",
    }
    claims.update(changes)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


def test_a_valid_token_gives_the_user(key: Any) -> None:
    user = _verifier(key).verify(_token(key))
    assert (user.id, user.name) == ("user-1", "thomas")


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": time.time() - 10},
        {"iss": "https://evil.example/realms/x"},
        {"azp": "some-other-app"},
        {"sub": None},
        {"exp": None},
    ],
)
def test_a_token_that_does_not_fit_is_refused(key: Any, changes: dict[str, Any]) -> None:
    with pytest.raises(jwt.PyJWTError):
        _verifier(key).verify(_token(key, **changes))


def test_a_token_signed_with_another_key_is_refused(key: Any) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        _verifier(key).verify(_token(other))


def test_an_unsigned_token_is_refused(key: Any) -> None:
    token = jwt.encode({"iss": ISSUER, "sub": "x", "exp": time.time() + 300}, None, algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        _verifier(key).verify(token)


def test_authenticate_turns_failures_into_problems(key: Any) -> None:
    verifier = _verifier(key)
    assert authenticate(verifier, f"Bearer {_token(key)}").id == "user-1"
    for header in (None, "", "Bearer", "Basic abc", f"Bearer {_token(key, exp=time.time() - 10)}"):
        with pytest.raises(Problem) as caught:
            authenticate(verifier, header)
        assert caught.value.status == 401


def test_bearer_token() -> None:
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer abc") == "abc"
    assert bearer_token("Token abc") is None
