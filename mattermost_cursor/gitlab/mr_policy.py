"""GitLab MR target-branch policy (port of gitlab/mr-policy.ts)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import AppEnv


def parse_forbidden_target_branches(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def is_forbidden_mr_target(branch: str, forbidden: list[str]) -> bool:
    lower = branch.lower()
    return any(f.lower() == lower for f in forbidden)


def resolve_mr_target_branch(
    specified: str | None, default_branch: str, forbidden: list[str],
) -> str:
    """Default when omitted, specified when allowed, default when forbidden."""
    trimmed = (specified or "").strip()
    if not trimmed:
        return default_branch
    if is_forbidden_mr_target(trimmed, forbidden):
        return default_branch
    return trimmed


def gitlab_mr_target_branch_instructions(env: "AppEnv") -> str:
    default_branch = env.GITLAB_MR_DEFAULT_TARGET_BRANCH
    forbidden = parse_forbidden_target_branches(env.GITLAB_MR_FORBIDDEN_TARGET_BRANCHES)
    forbidden_list = ", ".join(f"`{b}`" for b in forbidden)

    return (
        f"**GitLab merge request target branch:** Default target is `{default_branch}`. "
        f"When the user or task names a target branch, use that branch — but {forbidden_list} "
        f"must NEVER be used as the MR target branch. "
        f"If the requested target is forbidden, use `{default_branch}` instead and mention "
        f"the substitution briefly."
    )
