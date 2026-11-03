from typing import Optional
from ninja import Router

from backend.common.schemas import (
    GroupAddMemberRequestSchema,
    GroupCreateRequestSchema,
    GroupMealLogRequestSchema,
    GroupRequestRespondSchema,
)
from backend.groups.services import (
    add_member_to_group,
    create_nutrition_group,
    get_group_detail,
    join_public_group,
    list_groups_for_user,
    list_user_group_notifications,
    log_meal_to_group,
    respond_to_group_request,
)
from backend.profile.services import get_user_from_request

groups_router = Router(tags=["Nutrition Groups"])


@groups_router.get("", summary="List user's nutrition groups and public groups")
def api_list_groups(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
    q: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    return list_groups_for_user(current_user=user, search_query=q)


@groups_router.post("", summary="Create a public or private nutrition group")
def api_create_group(request, payload: GroupCreateRequestSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    combined_members = list(payload.member_identifiers or []) + list(payload.members or [])
    return create_nutrition_group(
        user,
        name=payload.name,
        description=payload.description,
        is_public=payload.is_public,
        visibility=payload.visibility,
        member_identifiers=combined_members,
    )


@groups_router.get("/notifications", summary="List user's group invitations and pending requests")
def api_group_notifications(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return list_user_group_notifications(user)


@groups_router.post("/requests/{request_id}/respond", summary="Accept, decline, or cancel a group membership request or invitation")
def api_respond_group_request(
    request,
    request_id: str,
    payload: GroupRequestRespondSchema,
):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    return respond_to_group_request(user, request_id=request_id, action=payload.action)


@groups_router.get("/{group_id}", summary="Get group details, members, and collective nutrition")
def api_get_group(
    request,
    group_id: str,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    return get_group_detail(group_id, current_user=user)


@groups_router.post("/{group_id}/members", summary="Add a member to a nutrition group by username or email")
def api_add_group_member(request, group_id: str, payload: GroupAddMemberRequestSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    ident = (payload.identifier or payload.username or payload.email or "").strip()
    return add_member_to_group(user, group_id=group_id, identifier=ident)


@groups_router.post("/{group_id}/join", summary="Join a public nutrition group")
def api_join_group(
    request,
    group_id: str,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return join_public_group(user, group_id=group_id)


@groups_router.post("/{group_id}/meals", summary="Log a meal to a group for collective nutrition tracking")
def api_log_group_meal(request, group_id: str, payload: GroupMealLogRequestSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    fat_val = payload.total_fat_g if payload.total_fat_g is not None else payload.fat_g
    fiber_val = payload.dietary_fiber_g if payload.dietary_fiber_g is not None else payload.fiber_g
    notes_val = payload.serving_notes or ""
    if payload.serving_grams is not None and not notes_val:
        notes_val = f"{payload.serving_grams}g"
    return log_meal_to_group(
        user,
        group_id=group_id,
        meal_title=payload.meal_title,
        meal_type=payload.meal_type,
        calories_kcal=payload.calories_kcal,
        protein_g=payload.protein_g,
        carbohydrates_g=payload.carbohydrates_g,
        total_fat_g=fat_val,
        dietary_fiber_g=fiber_val,
        serving_grams=payload.serving_grams,
        serving_notes=notes_val,
    )
