"""Shared helpers for the v1 routers."""
from __future__ import annotations

from fastapi import Request


def who(request: Request) -> str:
    """The acting person: the authenticated token's owner, never a body field
    (the guard middleware sets request.state.user)."""
    return getattr(request.state, "user", None) or "local-user"
