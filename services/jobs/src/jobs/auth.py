"""Who is asking: checks the access token of the identity provider (Keycloak, OpenID Connect).

The browser logs in at the identity provider and sends the access token with every request. This service only
verifies the token (signature with the public keys of the provider, issuer, expiry) and takes the user id from it. It
never sees a password and keeps no sessions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from .common import Problem

log = logging.getLogger("jobs.auth")


@dataclass(frozen=True)
class User:
    #: The ``sub`` claim: stable and unique for an account, the owner of its jobs.
    id: str
    #: Name to show, may be empty.
    name: str = ""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> User:
        """The user of a valid access token. Raises ``jwt.PyJWTError`` for anything else."""
        ...


class OidcVerifier:
    """Verifies RS256/ES256 access tokens against the key set (JWKS) of the identity provider."""

    def __init__(self, issuer: str, jwks_url: str, clients: tuple[str, ...]) -> None:
        self.issuer = issuer
        self.clients = clients
        self._keys = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=5)

    def verify(self, token: str) -> User:
        key = self._keys.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "ES256"],
            issuer=self.issuer,
            options={"require": ["exp", "sub", "iss"], "verify_aud": False},
        )
        # the token must have been issued to one of our own clients (``azp``), not to some other application
        if self.clients and claims.get("azp") not in self.clients:
            raise jwt.InvalidTokenError("The token was issued to another client.")
        name = claims.get("preferred_username") or claims.get("name") or claims.get("email") or ""
        return User(id=str(claims["sub"]), name=str(name))


def bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def authenticate(verifier: TokenVerifier, header: str | None) -> User:
    """The user for an ``Authorization`` header, or a 401 problem."""
    token = bearer_token(header)
    if token is None:
        raise Problem(401, "jobs.unauthorized", "Log in to use this service.", {"WWW-Authenticate": "Bearer"})
    try:
        return verifier.verify(token)
    except jwt.PyJWTError as exc:
        log.info("Token refused: %s", exc)
        raise Problem(
            401, "jobs.unauthorized", "The login is not valid or has expired.", {"WWW-Authenticate": "Bearer"}
        ) from exc
    except Exception as exc:  # the key set could not be fetched, the provider is down
        log.error("Token check failed: %s", exc)
        raise Problem(503, "jobs.auth_unavailable", "The login service is not reachable. Try again later.") from exc
