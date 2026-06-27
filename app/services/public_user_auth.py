"""
Public User MCP Auth — verifies usr_ tokens by calling NestJS BE.

This module handles authentication for public end-users connecting
their personal AI (Claude Desktop, ChatGPT Web, etc.) to the Heritage
MCP server. Employee (emp_/ark_) tokens continue to use the existing
MCPAuthService flow.

Architecture:
    User's AI Client -> MCP (Bearer usr_xxx) -> _verify_public_user_token()
                                                   -> NestJS BE POST /api/mcp-tokens/verify
                                                   -> Returns user context
"""

from dataclasses import dataclass, field
from typing import Optional

import httpx
from loguru import logger

from app.config import settings


@dataclass
class PublicUserIdentity:
    """Authenticated public user context, passed to MCP tools."""
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar: Optional[str] = None
    is_public_user: bool = True
    is_admin: bool = False

    # Compatibility with existing tool guards
    allowed_knowledge_types: Optional[list[str]] = None  # None = public only
    allowed_source_ids: Optional[list[str]] = None
    project_source_ids: list[str] = field(default_factory=list)


# In-memory cache: token -> (identity, expiry_time)
_cache: dict[str, tuple[PublicUserIdentity, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


async def verify_public_user_token(token: str) -> Optional[PublicUserIdentity]:
    """
    Verify a usr_ token by calling the Heritage NestJS backend.
    Returns PublicUserIdentity or None if invalid.
    """
    import time

    # Check cache first
    cached = _cache.get(token)
    if cached:
        identity, expiry = cached
        if time.time() < expiry:
            return identity
        del _cache[token]

    # Call NestJS BE to verify
    nestjs_url = settings.heritage_be_url.rstrip("/")
    service_token = settings.heritage_service_token

    if not service_token:
        logger.warning("HERITAGE_SERVICE_TOKEN not set, cannot verify public user tokens")
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{nestjs_url}/api/mcp-tokens/verify",
                json={"token": token},
                headers={"x-service-token": service_token},
            )
            if resp.status_code != 200:
                logger.warning(f"NestJS token verify returned {resp.status_code}")
                return None

            body = resp.json()
            user_data = body.get("data")
            if not user_data:
                return None

            identity = PublicUserIdentity(
                user_id=user_data["userId"],
                email=user_data.get("email"),
                name=user_data.get("name"),
                avatar=user_data.get("avatar"),
            )

            # Cache the result
            _cache[token] = (identity, time.time() + _CACHE_TTL_SECONDS)
            logger.info(f"Public user authenticated: {identity.email or identity.user_id}")
            return identity

    except httpx.RequestError as exc:
        logger.error(f"Failed to verify public user token: {exc}")
        return None
