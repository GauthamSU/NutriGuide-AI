import base64
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from ninja.errors import HttpError

from backend.assistant.models import ChatMessage
from backend.groups.models import (
    GroupMealLog,
    GroupMembership,
    GroupMembershipRequest,
    NutritionGroup,
)
from backend.profile.models import UserProfile
from backend.profile.services import (
    ensure_user_profile,
    get_profile_picture_url,
    get_user_from_request,
)
from backend.tracker.models import TrackedMeal
from backend.food_database.services import (
    resolve_dish_nutrition_from_db,
    resolve_single_ingredient_from_db,
)

User = get_user_model()
DATABASE_ALIAS = 'default'

def _compute_member_nutrition(member_user, group: NutritionGroup) -> Dict[str, Any]:
    """
    Compute a member's nutrition contributions from:
    1) Direct GroupMealLog entries logged to this group
    2) Explicitly logged TrackedMeal entries in the member's personal tracker
    """
    profile = ensure_user_profile(member_user)
    totals = {
        "meals_count": 0,
        "calories_kcal": 0.0,
        "protein_g": 0.0,
        "carbohydrates_g": 0.0,
        "total_fat_g": 0.0,
        "dietary_fiber_g": 0.0,
    }
    recent_meals: List[Dict[str, Any]] = []
    seen_identifiers = set()

    # 1. Group-specific meal logs
    group_logs = GroupMealLog.objects.filter(group=group, user=member_user).order_by("-created_at")
    for log in group_logs:
        cals = float(log.calories_kcal or 0.0)
        prot = float(log.protein_g or 0.0)
        carbs = float(log.carbohydrates_g or 0.0)
        fat = float(log.total_fat_g or 0.0)
        fiber = float(log.dietary_fiber_g or 0.0)

        # Ignore empty/deleted entries with 0 calories and 0 macros
        if cals <= 0 and prot <= 0 and carbs <= 0 and fat <= 0:
            continue

        clean_title = (log.meal_title or "").strip().lower()
        dedup_key = f"{clean_title}_{log.created_at.strftime('%Y-%m-%d_%H:%M')}"
        if dedup_key in seen_identifiers:
            continue
        seen_identifiers.add(dedup_key)

        totals["meals_count"] += 1
        totals["calories_kcal"] += cals
        totals["protein_g"] += prot
        totals["carbohydrates_g"] += carbs
        totals["total_fat_g"] += fat
        totals["dietary_fiber_g"] += fiber
        pic_url = get_profile_picture_url(profile)
        user_dict = {
            "username": member_user.username,
            "name": profile.name or member_user.username,
            "profile_picture": pic_url,
        }
        recent_meals.append({
            "id": str(log.id),
            "source": "group_log",
            "username": member_user.username,
            "member_name": profile.name or member_user.username,
            "profile_picture": pic_url,
            "user": user_dict,
            "meal_title": log.meal_title,
            "meal_type": log.meal_type,
            "calories_kcal": round(float(log.calories_kcal or 0.0), 1),
            "protein_g": round(float(log.protein_g or 0.0), 1),
            "carbohydrates_g": round(float(log.carbohydrates_g or 0.0), 1),
            "total_fat_g": round(float(log.total_fat_g or 0.0), 1),
            "dietary_fiber_g": round(float(log.dietary_fiber_g or 0.0), 1),
            "serving_notes": log.serving_notes,
            "created_at": log.created_at.isoformat(),
        })

    # 2. Member's explicitly logged TrackedMeal entries (NOT unlogged chat queries)
    tracked_meals = (
        TrackedMeal.objects.filter(
            Q(user=member_user) | Q(owner_id=str(profile.owner_id))
        )
        .order_by("-created_at")[:25]
    )
    for tm in tracked_meals:
        macros = tm.macronutrients or {}
        cals = float(macros.get("calories_kcal") or 0.0)
        prot = float(macros.get("protein_g") or 0.0)
        carbs = float(macros.get("carbohydrates_g") or 0.0)
        fat = float(macros.get("total_fat_g") or 0.0)
        fiber = float(macros.get("dietary_fiber_g") or 0.0)

        # Ignore empty/deleted entries with 0 calories and 0 macros
        if cals <= 0 and prot <= 0 and carbs <= 0 and fat <= 0:
            continue

        clean_title = (tm.meal_title or "").strip().lower()
        if tm.source_message_id:
            msg_key = f"msg_{tm.source_message_id}"
            if msg_key in seen_identifiers:
                continue
            seen_identifiers.add(msg_key)

        dedup_key = f"{clean_title}_{tm.created_at.strftime('%Y-%m-%d_%H:%M')}"
        if dedup_key in seen_identifiers:
            continue
        seen_identifiers.add(dedup_key)

        totals["meals_count"] += 1
        totals["calories_kcal"] += cals
        totals["protein_g"] += prot
        totals["carbohydrates_g"] += carbs
        totals["total_fat_g"] += fat
        totals["dietary_fiber_g"] += fiber

        pic_url = get_profile_picture_url(profile)
        user_dict = {
            "username": member_user.username,
            "name": profile.name or member_user.username,
            "profile_picture": pic_url,
        }
        recent_meals.append({
            "id": str(tm.id),
            "source": "tracked_meal",
            "username": member_user.username,
            "member_name": profile.name or member_user.username,
            "profile_picture": pic_url,
            "user": user_dict,
            "meal_title": tm.meal_title or "Logged Meal",
            "meal_type": tm.meal_type or "Logged Meal",
            "calories_kcal": round(cals, 1),
            "protein_g": round(prot, 1),
            "carbohydrates_g": round(carbs, 1),
            "total_fat_g": round(fat, 1),
            "dietary_fiber_g": round(fiber, 1),
            "serving_notes": tm.recognized_summary or "",
            "created_at": tm.created_at.isoformat(),
        })

    for key in ("calories_kcal", "protein_g", "carbohydrates_g", "total_fat_g", "dietary_fiber_g"):
        totals[key] = round(totals[key], 1)

    return {
        "totals": totals,
        "recent_meals": recent_meals,
    }


def serialize_membership_request(req: GroupMembershipRequest, current_user=None) -> Dict[str, Any]:
    """Serialize a GroupMembershipRequest for API responses and templates."""
    user_prof = getattr(req.user, "profile", None)
    return {
        "id": str(req.id),
        "group_id": str(req.group.id),
        "group_name": req.group.name,
        "group_description": req.group.description or "",
        "user_id": req.user.id,
        "username": req.user.username,
        "user_name": (user_prof.name if user_prof and user_prof.name else req.user.username),
        "user_profile_picture": get_profile_picture_url(user_prof) if user_prof else None,
        "created_by": req.created_by.username,
        "request_type": req.request_type,
        "status": req.status,
        "created_at": req.created_at.isoformat(),
    }


def serialize_group_summary(group: NutritionGroup, current_user=None) -> Dict[str, Any]:
    """Serialize a lightweight summary of a group for directory/list views."""
    memberships = list(
        GroupMembership.objects.filter(group=group).select_related("user", "user__profile")
    )
    is_member = any(m.user_id == getattr(current_user, "id", None) for m in memberships)
    total_cals = 0.0
    total_protein = 0.0
    total_meals = 0
    for m in memberships:
        stats = _compute_member_nutrition(m.user, group)["totals"]
        total_cals += stats["calories_kcal"]
        total_protein += stats["protein_g"]
        total_meals += stats["meals_count"]

    has_pending_join_request = False
    has_pending_invitation = False
    pending_request_id = None
    if current_user and not is_member:
        req = GroupMembershipRequest.objects.filter(
            group=group,
            user=current_user,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).first()
        if req:
            pending_request_id = str(req.id)
            if req.request_type == GroupMembershipRequest.TYPE_JOIN_REQUEST:
                has_pending_join_request = True
            elif req.request_type == GroupMembershipRequest.TYPE_INVITATION:
                has_pending_invitation = True

    is_admin = False
    if current_user and getattr(current_user, "id", None):
        is_admin = group.created_by_id == current_user.id or any(
            m.user_id == current_user.id and m.role == GroupMembership.ROLE_ADMIN
            for m in memberships
        )

    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "is_public": group.is_public,
        "visibility": "public" if group.is_public else "private",
        "created_by": group.created_by.username,
        "member_count": len(memberships),
        "is_member": is_member or is_admin,
        "is_admin": is_admin,
        "has_pending_join_request": has_pending_join_request,
        "has_pending_invitation": has_pending_invitation,
        "pending_request_id": pending_request_id,
        "total_meals_count": total_meals,
        "total_calories_kcal": round(total_cals, 1),
        "total_protein_g": round(total_protein, 1),
        "created_at": group.created_at.isoformat(),
    }


def get_group_detail(group_id: str, current_user=None) -> Dict[str, Any]:
    """Return full details of a group including member breakdown and collective nutrition."""
    try:
        group_uuid = uuid.UUID(str(group_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid group ID.") from exc

    group = (
        NutritionGroup.objects.select_related("created_by")
        .filter(id=group_uuid)
        .first()
    )
    if group is None:
        raise HttpError(404, "Group not found.")

    memberships = list(
        GroupMembership.objects.filter(group=group)
        .select_related("user", "user__profile")
        .order_by("joined_at")
    )
    is_member = any(m.user_id == getattr(current_user, "id", None) for m in memberships)

    if not group.is_public and not is_member:
        raise HttpError(403, "This is a private group. Only group members can view it.")

    members_data: List[Dict[str, Any]] = []
    all_recent_meals: List[Dict[str, Any]] = []
    collective = {
        "total_members": len(memberships),
        "total_meals_count": 0,
        "total_calories_kcal": 0.0,
        "total_protein_g": 0.0,
        "total_carbohydrates_g": 0.0,
        "total_fat_g": 0.0,
        "total_fiber_g": 0.0,
        "average_calories_per_member": 0.0,
    }

    for membership in memberships:
        m_user = membership.user
        m_profile = ensure_user_profile(m_user)
        m_Usage = _compute_member_nutrition(m_user, group)
        m_totals = m_Usage["totals"]
        all_recent_meals.extend(m_Usage["recent_meals"])

        collective["total_meals_count"] += m_totals["meals_count"]
        collective["total_calories_kcal"] += m_totals["calories_kcal"]
        collective["total_protein_g"] += m_totals["protein_g"]
        collective["total_carbohydrates_g"] += m_totals["carbohydrates_g"]
        collective["total_fat_g"] += m_totals["total_fat_g"]
        collective["total_fiber_g"] += m_totals["dietary_fiber_g"]

        members_data.append({
            "user_id": m_user.id,
            "username": m_user.username,
            "name": m_profile.name or m_user.username,
            "profile_picture": get_profile_picture_url(m_profile),
            "role": membership.role,
            "joined_at": membership.joined_at.isoformat(),
            "nutrition": m_totals,
        })

    for key in (
        "total_calories_kcal",
        "total_protein_g",
        "total_carbohydrates_g",
        "total_fat_g",
        "total_fiber_g",
    ):
        collective[key] = round(collective[key], 1)

    if collective["total_members"] > 0:
        collective["average_calories_per_member"] = round(
            collective["total_calories_kcal"] / collective["total_members"], 1
        )
    collective["total_meals_logged"] = collective["total_meals_count"]

    all_recent_meals.sort(key=lambda item: item["created_at"], reverse=True)

    is_admin = False
    if current_user and getattr(current_user, "id", None):
        is_admin = group.created_by_id == current_user.id or any(
            m.user_id == current_user.id and m.role == GroupMembership.ROLE_ADMIN
            for m in memberships
        )

    pending_join_requests = []
    pending_invitations = []
    if is_admin:
        join_reqs = GroupMembershipRequest.objects.filter(
            group=group,
            request_type=GroupMembershipRequest.TYPE_JOIN_REQUEST,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).select_related("group", "user", "user__profile", "created_by")
        pending_join_requests = [serialize_membership_request(r) for r in join_reqs]

        inv_reqs = GroupMembershipRequest.objects.filter(
            group=group,
            request_type=GroupMembershipRequest.TYPE_INVITATION,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).select_related("group", "user", "user__profile", "created_by")
        pending_invitations = [serialize_membership_request(r) for r in inv_reqs]

    has_pending_join_request = False
    has_pending_invitation = False
    pending_request_id = None
    if current_user and not is_member and getattr(current_user, "id", None):
        req = GroupMembershipRequest.objects.filter(
            group=group,
            user=current_user,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).first()
        if req:
            pending_request_id = str(req.id)
            if req.request_type == GroupMembershipRequest.TYPE_JOIN_REQUEST:
                has_pending_join_request = True
            elif req.request_type == GroupMembershipRequest.TYPE_INVITATION:
                has_pending_invitation = True

    base_group = {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "is_public": group.is_public,
        "visibility": "public" if group.is_public else "private",
        "created_by": group.created_by.username,
        "is_member": is_member,
        "is_admin": is_admin,
        "member_count": len(memberships),
        "created_at": group.created_at.isoformat(),
        "collective": collective,
        "collective_nutrition": collective,
        "members": members_data,
        "member_breakdown": members_data,
        "recent_meals": all_recent_meals[:25],
        "pending_join_requests": pending_join_requests,
        "pending_invitations": pending_invitations,
        "has_pending_join_request": has_pending_join_request,
        "has_pending_invitation": has_pending_invitation,
        "pending_request_id": pending_request_id,
    }
    result = dict(base_group)
    result["group"] = dict(base_group)
    return result


def create_nutrition_group(
    user,
    *,
    name: str,
    description: str = "",
    is_public: Optional[bool] = None,
    visibility: Optional[str] = None,
    member_identifiers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a new public or private nutrition group.
    Public group names must be unique (case-insensitive).
    """
    clean_name = (name or "").strip()
    clean_desc = (description or "").strip()

    if not clean_name:
        raise HttpError(400, "Group name is required.")
    if len(clean_name) > 120:
        raise HttpError(400, "Group name must be 120 characters or fewer.")

    if visibility is not None and str(visibility).strip():
        vis_norm = str(visibility).strip().lower()
        if vis_norm not in {"public", "private"}:
            raise HttpError(400, "Visibility must be either 'public' or 'private'.")
        resolved_public = vis_norm == "public"
    elif is_public is not None:
        resolved_public = bool(is_public)
    else:
        resolved_public = True

    if resolved_public:
        if NutritionGroup.objects.filter(is_public=True, name__iexact=clean_name).exists():
            raise HttpError(
                400,
                f"A public group named '{clean_name}' already exists. Public group names must be unique.",
            )

    try:
        with transaction.atomic():
            group = NutritionGroup.objects.create(
                name=clean_name,
                description=clean_desc,
                is_public=resolved_public,
                created_by=user,
            )
            GroupMembership.objects.create(
                group=group,
                user=user,
                role=GroupMembership.ROLE_ADMIN,
                added_by=user,
            )

            if member_identifiers:
                for raw_ident in member_identifiers:
                    for ident in re.split(r"[,;\s]+", str(raw_ident or "")):
                        ident = ident.strip()
                        if not ident:
                            continue
                        target = User.objects.filter(
                            Q(username__iexact=ident) | Q(email__iexact=ident)
                        ).first()
                        if target and target.id != user.id:
                            GroupMembershipRequest.objects.get_or_create(
                                group=group,
                                user=target,
                                defaults={
                                    "created_by": user,
                                    "request_type": GroupMembershipRequest.TYPE_INVITATION,
                                    "status": GroupMembershipRequest.STATUS_PENDING,
                                },
                            )
    except IntegrityError as exc:
        raise HttpError(
            400,
            f"A public group named '{clean_name}' already exists. Public group names must be unique.",
        ) from exc

    return get_group_detail(str(group.id), current_user=user)


def list_groups_for_user(current_user=None, search_query: Optional[str] = None) -> Dict[str, Any]:
    """Return user's groups, discoverable public groups, and pending invitations / join requests."""
    clean_q = (search_query or "").strip()
    my_groups = []
    pending_invitations = []
    my_pending_join_requests = []
    admin_pending_requests = []

    if current_user is not None and getattr(current_user, "is_authenticated", True):
        my_group_ids = (
            GroupMembership.objects.filter(user=current_user)
            .values_list("group_id", flat=True)
        )
        my_qs = NutritionGroup.objects.filter(
            Q(id__in=my_group_ids) | Q(created_by=current_user)
        ).distinct().select_related("created_by")
        if clean_q:
            my_qs = my_qs.filter(Q(name__icontains=clean_q) | Q(description__icontains=clean_q))
        for grp in my_qs:
            my_groups.append(serialize_group_summary(grp, current_user=current_user))

        # Invitations to current_user
        inv_qs = GroupMembershipRequest.objects.filter(
            user=current_user,
            request_type=GroupMembershipRequest.TYPE_INVITATION,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).select_related("group", "created_by", "user", "user__profile")
        pending_invitations = [serialize_membership_request(r, current_user=current_user) for r in inv_qs]

        # Join requests sent by current_user
        join_qs = GroupMembershipRequest.objects.filter(
            user=current_user,
            request_type=GroupMembershipRequest.TYPE_JOIN_REQUEST,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).select_related("group", "created_by", "user", "user__profile")
        my_pending_join_requests = [serialize_membership_request(r, current_user=current_user) for r in join_qs]

        # Join requests for groups current_user admins
        admin_group_ids = list(
            GroupMembership.objects.filter(user=current_user, role=GroupMembership.ROLE_ADMIN)
            .values_list("group_id", flat=True)
        )
        creator_group_ids = list(
            NutritionGroup.objects.filter(created_by=current_user).values_list("id", flat=True)
        )
        all_admin_ids = set(admin_group_ids) | set(creator_group_ids)
        admin_req_qs = GroupMembershipRequest.objects.filter(
            group_id__in=all_admin_ids,
            request_type=GroupMembershipRequest.TYPE_JOIN_REQUEST,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).select_related("group", "user", "user__profile", "created_by")
        admin_pending_requests = [serialize_membership_request(r, current_user=current_user) for r in admin_req_qs]

    pub_qs = (
        NutritionGroup.objects.filter(is_public=True)
        .annotate(num_members=Count("memberships"))
        .select_related("created_by")
    )
    if clean_q:
        pub_qs = pub_qs.filter(Q(name__icontains=clean_q) | Q(description__icontains=clean_q))
    pub_qs = pub_qs.order_by("-num_members", "-created_at")
    public_groups = [
        serialize_group_summary(grp, current_user=current_user)
        for grp in pub_qs[:3]
    ]

    notifications_count = len(pending_invitations) + len(admin_pending_requests)

    return {
        "my_groups": my_groups,
        "public_groups": public_groups,
        "query": clean_q,
        "pending_invitations": pending_invitations,
        "my_pending_join_requests": my_pending_join_requests,
        "admin_pending_requests": admin_pending_requests,
        "notifications_count": notifications_count,
    }


def add_member_to_group(
    acting_user,
    *,
    group_id: str,
    identifier: str,
) -> Dict[str, Any]:
    """Invite users by username or email. Creates invitations requiring user acceptance."""
    try:
        group_uuid = uuid.UUID(str(group_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid group ID.") from exc

    group = NutritionGroup.objects.filter(id=group_uuid).first()
    if group is None:
        raise HttpError(404, "Group not found.")

    is_member = GroupMembership.objects.filter(group=group, user=acting_user).exists()
    if not is_member and group.created_by_id != acting_user.id:
        raise HttpError(403, "Only members of this group can invite new members.")

    raw_identifiers = [
        part.strip()
        for part in re.split(r"[,;]+", identifier or "")
        if part.strip()
    ]
    if not raw_identifiers:
        raise HttpError(400, "Enter a username or email address to add a member.")

    invited_users = []
    already_members = []
    already_invited = []
    not_found = []

    for ident in raw_identifiers:
        clean_ident = ident.lstrip("@").strip()
        target = User.objects.filter(
            Q(username__iexact=clean_ident) | Q(email__iexact=clean_ident)
        ).first()
        if target is None:
            not_found.append(ident)
            continue
        ensure_user_profile(target)

        # 1. Already a member?
        if GroupMembership.objects.filter(group=group, user=target).exists():
            already_members.append(target.username)
            continue

        # 2. Did target already send a join request? Auto-approve it!
        pending_join = GroupMembershipRequest.objects.filter(
            group=group,
            user=target,
            request_type=GroupMembershipRequest.TYPE_JOIN_REQUEST,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).first()
        if pending_join:
            GroupMembership.objects.get_or_create(
                group=group,
                user=target,
                defaults={"role": GroupMembership.ROLE_MEMBER, "added_by": acting_user},
            )
            pending_join.status = GroupMembershipRequest.STATUS_ACCEPTED
            pending_join.responded_by = acting_user
            pending_join.save()
            invited_users.append(target.username)
            continue

        # 3. Already invited?
        existing_invite = GroupMembershipRequest.objects.filter(
            group=group,
            user=target,
            request_type=GroupMembershipRequest.TYPE_INVITATION,
            status=GroupMembershipRequest.STATUS_PENDING,
        ).first()
        if existing_invite:
            already_invited.append(target.username)
            continue

        # 4. Create pending invitation
        GroupMembershipRequest.objects.create(
            group=group,
            user=target,
            created_by=acting_user,
            request_type=GroupMembershipRequest.TYPE_INVITATION,
            status=GroupMembershipRequest.STATUS_PENDING,
        )
        invited_users.append(target.username)

    if not invited_users and not already_members and not already_invited and not_found:
        raise HttpError(
            404,
            f"User not found: {', '.join(not_found)}. Make sure they have created an account.",
        )

    msg_parts = []
    if invited_users:
        msg_parts.append(f"Invitation sent to {', '.join(f'@{u}' for u in invited_users)}. They will join once they accept.")
    if already_members:
        msg_parts.append(f"{', '.join(f'@{u}' for u in already_members)} is already a member.")
    if already_invited:
        msg_parts.append(f"Invitation already pending for {', '.join(f'@{u}' for u in already_invited)}.")
    if not_found:
        msg_parts.append(f"Could not find: {', '.join(not_found)}.")

    detail = get_group_detail(str(group.id), current_user=acting_user)
    detail["invited_members"] = invited_users
    detail["message"] = " ".join(msg_parts)
    return detail


def join_public_group(user, *, group_id: str) -> Dict[str, Any]:
    """Request to join a group. Creates a pending join request for admin approval."""
    try:
        group_uuid = uuid.UUID(str(group_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid group ID.") from exc

    group = NutritionGroup.objects.filter(id=group_uuid).first()
    if group is None:
        raise HttpError(404, "Group not found.")

    if not group.is_public and not GroupMembership.objects.filter(group=group, user=user).exists():
        raise HttpError(403, "This group is private. Ask a group member to invite you.")

    ensure_user_profile(user)

    # 1. Already a member?
    if GroupMembership.objects.filter(group=group, user=user).exists():
        detail = get_group_detail(str(group.id), current_user=user)
        detail["message"] = "You are already a member of this group."
        return detail

    # 2. Did admin invite user? Automatically accept!
    existing_invite = GroupMembershipRequest.objects.filter(
        group=group,
        user=user,
        request_type=GroupMembershipRequest.TYPE_INVITATION,
        status=GroupMembershipRequest.STATUS_PENDING,
    ).first()
    if existing_invite:
        GroupMembership.objects.get_or_create(
            group=group,
            user=user,
            defaults={"role": GroupMembership.ROLE_MEMBER, "added_by": existing_invite.created_by},
        )
        existing_invite.status = GroupMembershipRequest.STATUS_ACCEPTED
        existing_invite.responded_by = user
        existing_invite.save()
        detail = get_group_detail(str(group.id), current_user=user)
        detail["message"] = f"Invitation accepted! You are now a member of {group.name}."
        return detail

    # 3. Already requested?
    existing_request = GroupMembershipRequest.objects.filter(
        group=group,
        user=user,
        request_type=GroupMembershipRequest.TYPE_JOIN_REQUEST,
        status=GroupMembershipRequest.STATUS_PENDING,
    ).first()
    if existing_request:
        detail = get_group_detail(str(group.id), current_user=user)
        detail["message"] = "Your request to join is already pending admin approval."
        detail["has_pending_join_request"] = True
        detail["pending_request_id"] = str(existing_request.id)
        return detail

    # 4. Create join request
    join_req = GroupMembershipRequest.objects.create(
        group=group,
        user=user,
        created_by=user,
        request_type=GroupMembershipRequest.TYPE_JOIN_REQUEST,
        status=GroupMembershipRequest.STATUS_PENDING,
    )

    detail = get_group_detail(str(group.id), current_user=user)
    detail["message"] = f"Join request sent to the admin of {group.name}. You will be added once approved!"
    detail["has_pending_join_request"] = True
    detail["pending_request_id"] = str(join_req.id)
    return detail


def respond_to_group_request(
    acting_user,
    *,
    request_id: str,
    action: str,
) -> Dict[str, Any]:
    """Accept or reject a group invitation or join request."""
    try:
        req_uuid = uuid.UUID(str(request_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid request ID.") from exc

    req = GroupMembershipRequest.objects.filter(id=req_uuid).select_related("group", "user", "created_by").first()
    if req is None:
        raise HttpError(404, "Group request not found.")

    if req.status != GroupMembershipRequest.STATUS_PENDING:
        raise HttpError(400, f"This request has already been {req.status}.")

    clean_action = str(action or "").strip().lower()
    if clean_action not in {"accept", "approve", "reject", "decline", "cancel"}:
        raise HttpError(400, "Action must be 'accept' or 'reject'.")

    is_accept = clean_action in {"accept", "approve"}

    if req.request_type == GroupMembershipRequest.TYPE_INVITATION:
        # Target user receives invitation from admin
        if is_accept:
            if req.user_id != acting_user.id:
                raise HttpError(403, "Only the invited user can accept this invitation.")
            ensure_user_profile(acting_user)
            GroupMembership.objects.get_or_create(
                group=req.group,
                user=acting_user,
                defaults={
                    "role": GroupMembership.ROLE_MEMBER,
                    "added_by": req.created_by,
                },
            )
            req.status = GroupMembershipRequest.STATUS_ACCEPTED
            req.responded_by = acting_user
            req.save()
            msg = f"You have accepted the invitation and joined {req.group.name}!"
        else:
            is_admin = (
                GroupMembership.objects.filter(group=req.group, user=acting_user, role=GroupMembership.ROLE_ADMIN).exists()
                or req.group.created_by_id == acting_user.id
            )
            if req.user_id != acting_user.id and not is_admin:
                raise HttpError(403, "You do not have permission to reject or cancel this invitation.")
            req.status = GroupMembershipRequest.STATUS_REJECTED
            req.responded_by = acting_user
            req.save()
            msg = "Invitation declined." if req.user_id == acting_user.id else "Invitation revoked."

    elif req.request_type == GroupMembershipRequest.TYPE_JOIN_REQUEST:
        # User requested to join group -> Group admin/creator approves or rejects
        is_admin = (
            GroupMembership.objects.filter(group=req.group, user=acting_user, role=GroupMembership.ROLE_ADMIN).exists()
            or req.group.created_by_id == acting_user.id
        )
        if is_accept:
            if not is_admin:
                raise HttpError(403, "Only a group admin can approve join requests.")
            ensure_user_profile(req.user)
            GroupMembership.objects.get_or_create(
                group=req.group,
                user=req.user,
                defaults={
                    "role": GroupMembership.ROLE_MEMBER,
                    "added_by": acting_user,
                },
            )
            req.status = GroupMembershipRequest.STATUS_ACCEPTED
            req.responded_by = acting_user
            req.save()
            msg = f"Approved @{req.user.username}'s request to join {req.group.name}!"
        else:
            if not is_admin and req.user_id != acting_user.id:
                raise HttpError(403, "You do not have permission to reject or cancel this join request.")
            req.status = GroupMembershipRequest.STATUS_REJECTED
            req.responded_by = acting_user
            req.save()
            msg = "Join request canceled." if req.user_id == acting_user.id else f"Rejected @{req.user.username}'s join request."

    return {
        "success": True,
        "message": msg,
        "request_id": str(req.id),
        "status": req.status,
        "group_id": str(req.group.id),
        "group_name": req.group.name,
    }


def list_user_group_notifications(user) -> Dict[str, Any]:
    """Return all pending group invitations and join requests awaiting user/admin action."""
    if not user or not getattr(user, "is_authenticated", True):
        return {
            "pending_invitations": [],
            "my_pending_join_requests": [],
            "admin_pending_requests": [],
            "notifications_count": 0,
        }
    data = list_groups_for_user(current_user=user)
    return {
        "pending_invitations": data.get("pending_invitations", []),
        "my_pending_join_requests": data.get("my_pending_join_requests", []),
        "admin_pending_requests": data.get("admin_pending_requests", []),
        "notifications_count": data.get("notifications_count", 0),
    }


def log_meal_to_group(
    user,
    *,
    group_id: str,
    meal_title: str,
    meal_type: str = "Meal",
    calories_kcal: Optional[float] = None,
    protein_g: Optional[float] = None,
    carbohydrates_g: Optional[float] = None,
    total_fat_g: Optional[float] = None,
    dietary_fiber_g: Optional[float] = None,
    serving_grams: Optional[float] = None,
    serving_notes: str = "",
) -> Dict[str, Any]:
    """
    Log a meal entry to a group for collective nutrition tracking.
    If explicit calories/macros are omitted or zero, resolves food items against the IFCT database.
    """
    try:
        group_uuid = uuid.UUID(str(group_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid group ID.") from exc

    group = NutritionGroup.objects.filter(id=group_uuid).first()
    if group is None:
        raise HttpError(404, "Group not found.")

    if not GroupMembership.objects.filter(group=group, user=user).exists():
        raise HttpError(403, "You must be a member of this group to log meals.")

    clean_title = (meal_title or "").strip()
    if not clean_title:
        raise HttpError(400, "Meal name or description is required.")

    cals = float(calories_kcal or 0.0)
    prot = float(protein_g or 0.0)
    carbs = float(carbohydrates_g or 0.0)
    fat = float(total_fat_g or 0.0)
    fiber = float(dietary_fiber_g or 0.0)

    # Auto-resolve from IFCT database if calories are not manually provided
    if cals <= 0 and prot <= 0 and carbs <= 0 and fat <= 0:
        default_weight = float(serving_grams) if serving_grams and float(serving_grams) > 0 else None
        if default_weight is None and serving_notes:
            notes_weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gm|grams|ml)\b", serving_notes, flags=re.I)
            if notes_weight_match:
                default_weight = float(notes_weight_match.group(1))
        if default_weight is None:
            default_weight = 100.0

        parts = [p.strip() for p in re.split(r"[,;+]+|\band\b", clean_title) if p.strip()]
        for part in parts:
            weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gm|grams|ml)\b", part, flags=re.I)
            weight_g = float(weight_match.group(1)) if weight_match else default_weight
            food_name = re.sub(r"\b\d+(?:\.\d+)?\s*(?:g|gm|grams|ml)\b", "", part, flags=re.I).strip()
            if not food_name:
                food_name = part
            resolved_item, is_found = resolve_single_ingredient_from_db({
                "ingredient_name": food_name,
                "estimated_weight_grams": weight_g,
                "serving_size_description": f"{int(weight_g)}g",
            })
            if is_found:
                macros = resolved_item.get("macronutrients") or {}
                cals += float(macros.get("calories_kcal") or 0.0)
                prot += float(macros.get("protein_g") or 0.0)
                carbs += float(macros.get("carbohydrates_g") or 0.0)
                fat += float(macros.get("total_fat_g") or 0.0)
                fiber += float(macros.get("dietary_fiber_g") or 0.0)

    GroupMealLog.objects.create(
        group=group,
        user=user,
        meal_title=clean_title[:200],
        meal_type=(meal_type or "Meal").strip()[:32],
        calories_kcal=round(cals, 1),
        protein_g=round(prot, 1),
        carbohydrates_g=round(carbs, 1),
        total_fat_g=round(fat, 1),
        dietary_fiber_g=round(fiber, 1),
        serving_notes=(serving_notes or "").strip()[:1000],
    )
    return get_group_detail(str(group.id), current_user=user)


def delete_group_meal(user, group_id: str, meal_id: str) -> Dict[str, Any]:
    """
    Delete a meal entry displayed in a group feed.
    Can be a direct GroupMealLog or a member's TrackedMeal.
    Permitted if the caller is the author of the meal or a group admin.
    """
    try:
        g_uuid = uuid.UUID(str(group_id))
        m_uuid = uuid.UUID(str(meal_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid group or meal ID format.") from exc

    group = NutritionGroup.objects.filter(id=g_uuid).first()
    if not group:
        raise HttpError(404, "Group not found.")

    membership = GroupMembership.objects.filter(group=group, user=user).first()
    if not membership:
        raise HttpError(403, "You must be a member of this group.")

    is_admin = group.created_by_id == user.id or membership.role == GroupMembership.ROLE_ADMIN

    # 1. Check GroupMealLog
    gml = GroupMealLog.objects.filter(id=m_uuid, group=group).first()
    if gml:
        if not is_admin and gml.user_id != user.id:
            raise HttpError(403, "You can only delete your own meal entries.")
        gml.delete()
        return {"status": "ok", "deleted_id": str(m_uuid)}

    # 2. Check TrackedMeal
    tm = TrackedMeal.objects.filter(id=m_uuid).first()
    if tm:
        profile = ensure_user_profile(user)
        is_author = (tm.user_id == user.id) or (tm.owner_id == str(profile.owner_id))
        if not is_admin and not is_author:
            raise HttpError(403, "You can only delete your own meal entries.")
        source_msg_id = tm.source_message_id
        tm.delete()
        if source_msg_id:
            try:
                msg_uuid = uuid.UUID(source_msg_id)
                from chat_history.models import ChatMessage
                chat_msg = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=msg_uuid).first()
                if chat_msg and isinstance(chat_msg.ai_response, dict):
                    ai_resp = dict(chat_msg.ai_response)
                    ai_resp["logged_to_tracker"] = False
                    ai_resp.pop("tracker_log_id", None)
                    chat_msg.ai_response = ai_resp
                    chat_msg.save(using=DATABASE_ALIAS, update_fields=["ai_response"])
            except Exception:
                pass
        return {"status": "ok", "deleted_id": str(m_uuid)}

    raise HttpError(404, "Meal entry not found.")

