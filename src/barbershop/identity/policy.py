"""Deny-by-default authorization policy independent from HTTP transport."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID


class AccessAction(StrEnum):
    READ_BRANCH = "read_branch"
    MANAGE_BRANCH = "manage_branch"
    MARK_OUTCOME = "mark_outcome"


class AccessDenied(PermissionError):
    """Raised when a principal lacks authentication, role, or branch scope."""


@dataclass(frozen=True)
class Principal:
    """Trusted identity context; roles are never read from a request payload."""

    user_id: int
    roles: frozenset[str]
    branch_ids: frozenset[UUID]
    authenticated: bool = True


ROLE_ACTIONS: Final[dict[str, frozenset[AccessAction]]] = {
    "MASTER": frozenset({AccessAction.READ_BRANCH, AccessAction.MARK_OUTCOME}),
    "ADMIN": frozenset(
        {AccessAction.READ_BRANCH, AccessAction.MANAGE_BRANCH, AccessAction.MARK_OUTCOME}
    ),
    "OWNER": frozenset(AccessAction),
}


def authorize(principal: Principal | None, action: AccessAction, branch_id: UUID) -> None:
    """Authorize a staff action using only trusted identity and explicit scope."""
    if principal is None or not principal.authenticated:
        raise AccessDenied("authentication is required")
    if not principal.roles:
        raise AccessDenied("no staff role is assigned")

    for role in principal.roles:
        if action not in ROLE_ACTIONS.get(role, frozenset()):
            continue
        if role == "OWNER" or branch_id in principal.branch_ids:
            return
    raise AccessDenied("branch scope does not permit this action")
