"""
Backward-compatibility facade for user profile and groups services.
Modularly organized in:
- backend.profile.services (Auth, user profile, biometrics)
- backend.groups.services (Nutrition groups, memberships, collective meal logs)
"""

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
from backend.profile.services import (
    build_profile_context_for_ai,
    compute_bmi,
    create_auth_token,
    ensure_user_profile,
    get_profile_avatar,
    get_profile_picture_url,
    get_user_from_request,
    login_user,
    serialize_user_profile,
    signup_user,
    update_user_profile,
    validate_password_strength,
    verify_auth_token,
)

__all__ = [
    "ensure_user_profile",
    "create_auth_token",
    "verify_auth_token",
    "get_user_from_request",
    "validate_password_strength",
    "compute_bmi",
    "get_profile_picture_url",
    "get_profile_avatar",
    "serialize_user_profile",
    "signup_user",
    "login_user",
    "update_user_profile",
    "build_profile_context_for_ai",
    "get_group_detail",
    "create_nutrition_group",
    "list_groups_for_user",
    "add_member_to_group",
    "join_public_group",
    "respond_to_group_request",
    "list_user_group_notifications",
    "log_meal_to_group",
]
