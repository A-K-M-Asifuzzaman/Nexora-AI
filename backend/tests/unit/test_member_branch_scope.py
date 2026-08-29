"""Branch-scope escalation guards for MemberService (finding P1-25).

The escalation these cover: an actor restricted to one branch, holding
`users.manage_roles`, could set its own `branch_ids` to `[]`. No
`membership_branches` rows means *unrestricted*, so an empty list promoted the
actor from a single branch to every branch in the tenant — in one request.

`update_roles` had a self-modification guard; `update_branches` did not. These
tests pin both halves of the fix and, just as importantly, pin the paths that
must keep working.
"""

import uuid

import pytest

from app.core.context import TenantContext
from app.core.errors import PermissionDeniedError
from app.modules.members.service import MemberService

BRANCH_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
BRANCH_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
ACTOR_MEMBERSHIP = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
OTHER_MEMBERSHIP = uuid.UUID("dddddddd-0000-0000-0000-000000000004")


def _context(branch_ids: frozenset[uuid.UUID] | None) -> TenantContext:
    return TenantContext(
        tenant_id=uuid.uuid4(),
        membership_id=ACTOR_MEMBERSHIP,
        user_id=uuid.uuid4(),
        role_ids=frozenset(),
        permissions=frozenset({"users.manage_roles"}),
        branch_ids=branch_ids,
    )


def _guarded_service(branch_ids: frozenset[uuid.UUID] | None) -> MemberService:
    """Both guards run before any database access, so no session is needed.

    That is deliberate in the fix: rejecting an escalation should never depend on
    a database round trip succeeding first.
    """
    service = object.__new__(MemberService)
    service.context = _context(branch_ids)
    return service


async def test_cannot_widen_own_branch_scope_to_unrestricted() -> None:
    """The reported escalation: restricted actor sets its own scope to []."""
    service = _guarded_service(frozenset({BRANCH_A}))
    with pytest.raises(PermissionDeniedError) as exc:
        await service.update_branches(ACTOR_MEMBERSHIP, set())
    assert exc.value.code == "CANNOT_MODIFY_OWN_BRANCHES"


async def test_cannot_modify_own_branches_even_without_widening() -> None:
    service = _guarded_service(frozenset({BRANCH_A}))
    with pytest.raises(PermissionDeniedError) as exc:
        await service.update_branches(ACTOR_MEMBERSHIP, {BRANCH_A})
    assert exc.value.code == "CANNOT_MODIFY_OWN_BRANCHES"


def test_restricted_actor_cannot_grant_a_branch_it_lacks() -> None:
    service = _guarded_service(frozenset({BRANCH_A}))
    with pytest.raises(PermissionDeniedError) as exc:
        service._require_grantable_branches({BRANCH_B})
    assert exc.value.code == "CANNOT_GRANT_UNHELD_BRANCH"


def test_restricted_actor_cannot_make_another_member_unrestricted() -> None:
    """`[]` means unrestricted, so it must be refused for a restricted actor."""
    service = _guarded_service(frozenset({BRANCH_A}))
    with pytest.raises(PermissionDeniedError) as exc:
        service._require_grantable_branches(set())
    assert exc.value.code == "CANNOT_GRANT_UNHELD_BRANCH"


def test_restricted_actor_may_grant_a_branch_it_holds() -> None:
    service = _guarded_service(frozenset({BRANCH_A, BRANCH_B}))
    service._require_grantable_branches({BRANCH_A})


def test_unrestricted_actor_may_grant_any_branch() -> None:
    """Must not regress: an OWNER/ADMIN with no branch restriction keeps full reach."""
    service = _guarded_service(None)
    service._require_grantable_branches({BRANCH_A, BRANCH_B})


def test_unrestricted_actor_may_make_another_member_unrestricted() -> None:
    service = _guarded_service(None)
    service._require_grantable_branches(set())


def test_other_membership_is_not_blocked_by_the_self_guard() -> None:
    service = _guarded_service(frozenset({BRANCH_A}))
    assert OTHER_MEMBERSHIP != service.context.membership_id
    service._require_grantable_branches({BRANCH_A})
