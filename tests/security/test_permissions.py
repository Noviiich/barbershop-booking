"""AUTH-01: deny-by-default policy and branch scope isolation."""

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory

from barbershop.identity.models import StaffRole, StaffScope
from barbershop.identity.policy import AccessAction, AccessDenied, Principal, authorize

BRANCH_A = UUID("00000000-0000-0000-0000-00000000000a")
BRANCH_B = UUID("00000000-0000-0000-0000-00000000000b")


def test_admin_can_manage_only_the_assigned_branch() -> None:
    principal = Principal(7, frozenset({"ADMIN"}), frozenset({BRANCH_A}))

    authorize(principal, AccessAction.MANAGE_BRANCH, BRANCH_A)
    with pytest.raises(AccessDenied):
        authorize(principal, AccessAction.MANAGE_BRANCH, BRANCH_B)


def test_master_cannot_manage_catalog_and_unauthenticated_is_denied() -> None:
    master = Principal(8, frozenset({"MASTER"}), frozenset({BRANCH_A}))

    authorize(master, AccessAction.MARK_OUTCOME, BRANCH_A)
    with pytest.raises(AccessDenied):
        authorize(master, AccessAction.MANAGE_BRANCH, BRANCH_A)
    with pytest.raises(AccessDenied):
        authorize(None, AccessAction.READ_BRANCH, BRANCH_A)


def test_owner_scope_is_global_but_principal_is_immutable() -> None:
    owner = Principal(9, frozenset({"OWNER"}), frozenset())

    authorize(owner, AccessAction.MANAGE_BRANCH, BRANCH_B)
    with pytest.raises(FrozenInstanceError):
        owner.user_id = 10  # type: ignore[misc]


def test_model_has_one_global_owner_constraint_per_user() -> None:
    constraints = {constraint.name: constraint for constraint in StaffScope._meta.constraints}
    owner_constraint = constraints["identity_scope_one_global_owner_per_user"]

    assert owner_constraint.fields == ("user",)
    assert set(owner_constraint.condition.children) == {
        ("branch_id__isnull", True),
        ("role", StaffRole.OWNER),
    }


def test_session_and_csrf_middleware_are_enabled() -> None:
    assert "django.contrib.sessions.middleware.SessionMiddleware" in settings.MIDDLEWARE
    assert "django.contrib.auth.middleware.AuthenticationMiddleware" in settings.MIDDLEWARE
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE

    request = RequestFactory().post("/internal-mutation/")
    middleware = CsrfViewMiddleware(lambda _: HttpResponse("ok"))
    response = middleware.process_view(request, lambda _: HttpResponse("ok"), (), {})

    assert response.status_code == 403
