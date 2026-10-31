"""Row-level access control: users only ever see papers of groups they belong to.

Every view goes through these helpers — never `Paper.objects.all()` directly.
"""
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import GroupMembership, Paper, ResearchGroup

MANAGER_ROLES = (GroupMembership.Role.OWNER, GroupMembership.Role.ADMIN)
EDITOR_ROLES = MANAGER_ROLES + (GroupMembership.Role.MEMBER,)


def visible_groups(user):
    if user.is_superuser:
        return ResearchGroup.objects.all()
    return ResearchGroup.objects.filter(memberships__user=user).distinct()


def visible_papers(user):
    qs = Paper.objects.select_related("group", "lead")
    if user.is_superuser:
        return qs
    # External collaborators see only papers where they are an author or the lead.
    full_groups = GroupMembership.objects.filter(user=user, role__in=EDITOR_ROLES).values("group")
    from django.db.models import Q
    return qs.filter(
        Q(group__in=full_groups) | Q(authors__user=user) | Q(lead=user)
    ).distinct()


def role(user, group):
    if user.is_superuser:
        return GroupMembership.Role.OWNER
    return group.role_of(user)


def can_edit_paper(user, paper):
    r = role(user, paper.group)
    if r in EDITOR_ROLES:
        return True
    # External co-authors may edit papers they are on.
    return paper.lead_id == user.id or paper.authors.filter(user=user).exists()


def can_manage_group(user, group):
    return role(user, group) in MANAGER_ROLES


def get_paper_or_403(user, pk, edit=False):
    paper = get_object_or_404(Paper.objects.select_related("group", "lead"), pk=pk)
    if not visible_papers(user).filter(pk=pk).exists():
        raise PermissionDenied
    if edit and not can_edit_paper(user, paper):
        raise PermissionDenied
    return paper


def get_group_or_403(user, pk, manage=False):
    group = get_object_or_404(ResearchGroup, pk=pk)
    r = role(user, group)
    if r is None or (manage and r not in MANAGER_ROLES):
        raise PermissionDenied
    return group
