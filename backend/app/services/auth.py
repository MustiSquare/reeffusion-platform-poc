from dataclasses import dataclass
from typing import Callable

from fastapi import Header, HTTPException

from app.core.config import settings


ROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2}


@dataclass(frozen=True)
class Principal:
    role: str
    auth_enabled: bool


def _token_role(token: str | None) -> str | None:
    if not token:
        return None
    if token == settings.auth_admin_token:
        return "admin"
    if token == settings.auth_editor_token:
        return "editor"
    return None


def require_role(required_role: str = "viewer") -> Callable:
    required_rank = ROLE_ORDER[required_role]

    def dependency(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Principal:
        if not settings.auth_enabled:
            return Principal(role="admin", auth_enabled=False)

        bearer = None
        if authorization and authorization.lower().startswith("bearer "):
            bearer = authorization.split(" ", 1)[1].strip()
        role = _token_role(bearer or x_api_key)
        if role is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if ROLE_ORDER[role] < required_rank:
            raise HTTPException(status_code=403, detail=f"Role '{required_role}' required")
        return Principal(role=role, auth_enabled=True)

    return dependency
