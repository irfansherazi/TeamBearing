"""
vQA — SSO Authentication (RS256)
================================
Module: backend/auth/sso.py

Handles RS256 JWT validation using the public key from vcAPI.
Parses and validates the SsoToken structure.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import jwt
from pydantic import BaseModel

from backend.config import settings

logger = logging.getLogger(__name__)


class SsoToken(BaseModel):
    """
    Pydantic model for the vcAPI SSO Token structure.
    Matches the SsoToken interface in vcapi/src/shared/common/sso-token.ts.
    """

    model_config = {"extra": "ignore"}

    jti: str
    vc_guid: str
    email: str
    vc_id: int
    vc_status: int
    session_salt: str
    exp: Optional[int] = None
    identity_id: Optional[str] = None
    token: Optional[str] = None


class SsoValidator:
    """
    Validates RS256 JWTs against the vcAPI public key.
    """

    _public_key: Optional[str] = None

    @classmethod
    def get_public_key(cls) -> str:
        """
        Load and cache the RS256 public key.

        Priority:
        1. ``SSO_PUBLIC_KEY`` environment variable (inline PEM string).
        2. File at ``settings.sso_public_key_path`` (relative to CWD or backend root).
        """
        if cls._public_key:
            return cls._public_key

        # 1. Try inline env var first — preferred for containerised deployments
        import textwrap
        inline = (settings.sso_public_key or "").strip()
        if inline:
            # The value may be indented in the config; normalise to a clean PEM block.
            cls._public_key = textwrap.dedent(inline)
            logger.info("SSO public key loaded from SSO_PUBLIC_KEY env var (%d chars)", len(cls._public_key))
            return cls._public_key

        # 2. Fall back to file on disk
        key_path = Path(settings.sso_public_key_path)
        if not key_path.exists():
            # Try relative to the backend/ directory (parent of this file's parent)
            key_path = Path(__file__).parent.parent.parent / settings.sso_public_key_path

        if not key_path.exists():
            logger.error(
                "SSO Public Key not found. Set SSO_PUBLIC_KEY env var or place the key at %s.", key_path
            )
            raise FileNotFoundError(
                f"SSO Public Key not found. Set SSO_PUBLIC_KEY env var or place the key at {key_path}."
            )

        cls._public_key = key_path.read_text()
        logger.info("SSO public key loaded from file: %s (%d chars)", key_path, len(cls._public_key))
        return cls._public_key

    @classmethod
    def validate_token(cls, token: str) -> Optional[SsoToken]:
        """
        Validate a JWT token and return the SsoToken payload if successful.

        Phase 1 hardening (per-user-session-isolation, ADR-6):
          - Requires ``exp``, ``jti``, and ``vc_id`` claims (options={"require": [...]}).
          - Enforces MAX_JWT_TTL_SECONDS: rejects tokens where (exp - now) > limit.
          - Checks jti against RevokedJtiSet (if jti is revoked, returns None).
        """
        try:
            public_key = cls.get_public_key()
            # Peek at the JWT header so we can log the algorithm on failure
            try:
                header = jwt.get_unverified_header(token)
                alg = header.get("alg", "unknown")
            except Exception:
                alg = "unparseable"
            logger.debug("Validating SSO token with alg=%s", alg)
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={
                    "verify_exp": True,
                    "require": ["exp", "jti", "vc_id"],
                },
            )

            # --- Phase 1 hardening: enforce MAX_JWT_TTL_SECONDS ---
            max_ttl = int(os.environ.get("MAX_JWT_TTL_SECONDS", "3600"))
            exp = payload.get("exp")
            if exp is None:
                logger.warning("SSO Token missing exp claim — rejected")
                return None
            ttl = exp - time.time()
            if ttl > max_ttl:
                logger.warning(
                    "SSO Token TTL %.0fs exceeds MAX_JWT_TTL_SECONDS=%d — rejected",
                    ttl, max_ttl,
                )
                return None

            # --- Phase 1 hardening: check jti revocation ---
            jti = payload.get("jti")
            if jti:
                try:
                    from backend.auth.revocation import get_revocation_set
                    if get_revocation_set().is_revoked(jti):
                        logger.warning(
                            '{"event": "session.jti_revoked_hit", "jti": "%s"}', jti,
                        )
                        return None
                except Exception as rev_exc:
                    logger.debug("Revocation check failed (non-fatal): %s", rev_exc)

            return SsoToken(**payload)
        except jwt.ExpiredSignatureError:
            logger.warning("SSO Token has expired")
            return None
        except jwt.MissingRequiredClaimError as e:
            logger.warning("SSO Token missing required claim: %s", str(e))
            return None
        except jwt.InvalidTokenError as e:
            logger.error("SSO Token validation failed (InvalidTokenError): %s", str(e))
            return None
        except Exception as e:
            logger.error("SSO Token validation failed (unexpected): %s: %s", type(e).__name__, str(e))
            return None


validator = SsoValidator()
