import base64
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse
from ninja.errors import HttpError

from chat_history.models import (
    ChatMessage,
    GroupMealLog,
    GroupMembership,
    GroupMembershipRequest,
    NutritionGroup,
    TrackedMeal,
    UserProfile,
)
from nutrition.services.db_nutrition_service import (
    resolve_dish_nutrition_from_db,
    resolve_single_ingredient_from_db,
)

User = get_user_model()
AUTH_TOKEN_SALT = "nutriguide.auth.token"
AUTH_TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def ensure_user_profile(user, preferred_owner_id: Optional[str] = None) -> UserProfile:
    """Return the user's UserProfile, creating one if it does not exist."""
    profile = UserProfile.objects.filter(user=user).first()
    if profile is not None:
        return profile

    owner_uuid = uuid.uuid4()
    if preferred_owner_id:
        try:
            candidate = uuid.UUID(str(preferred_owner_id))
            if not UserProfile.objects.filter(owner_id=candidate).exists():
                owner_uuid = candidate
        except (ValueError, TypeError):
            pass

    profile = UserProfile.objects.create(
        user=user,
        owner_id=owner_uuid,
        name=user.get_full_name() or user.username,
    )
    return profile


def create_auth_token(user) -> str:
    """Create a signed authentication token for a user."""
    profile = ensure_user_profile(user)
    payload = {
        "user_id": user.id,
        "username": user.username,
        "owner_id": str(profile.owner_id),
    }
    return signing.dumps(payload, salt=AUTH_TOKEN_SALT)


def verify_auth_token(token: str):
    """Verify a signed authentication token and return the corresponding User or None."""
    if not token:
        return None
    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()
    try:
        payload = signing.loads(
            clean_token,
            salt=AUTH_TOKEN_SALT,
            max_age=AUTH_TOKEN_MAX_AGE,
        )
        user_id = payload.get("user_id")
        if not user_id:
            return None
        return User.objects.select_related("profile").filter(id=user_id, is_active=True).first()
    except signing.BadSignature:
        return None


def get_user_from_request(
    request,
    *,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
    require_auth: bool = False,
):
    """
    Resolve the authenticated User from headers, session, or signed token.
    Never creates or authenticates guest_* accounts. When require_auth=True,
    a valid authentication token or authenticated Django session is required.
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("X-Auth-Token") or token
    if auth_header:
        user = verify_auth_token(auth_header)
        if user is not None and not user.username.startswith("guest_"):
            return user

    if (
        hasattr(request, "user")
        and getattr(request.user, "is_authenticated", False)
        and not getattr(request.user, "username", "").startswith("guest_")
    ):
        return request.user

    if not require_auth and owner_id:
        try:
            owner_uuid = uuid.UUID(str(owner_id))
            profile = UserProfile.objects.select_related("user").filter(owner_id=owner_uuid).first()
            if (
                profile
                and profile.user.is_active
                and not profile.user.username.startswith("guest_")
            ):
                return profile.user
        except (ValueError, TypeError):
            pass

    if require_auth:
        raise HttpError(
            401,
            "Authentication required. Please log in or sign up before creating a profile or group.",
        )
    return None


def validate_password_strength(password: str) -> Dict[str, Any]:
    """
    Evaluate password strength criteria:
    - At least 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    - At least 1 special character
    """
    raw = password or ""
    checks = {
        "min_length": len(raw) >= 8,
        "has_uppercase": bool(re.search(r"[A-Z]", raw)),
        "has_lowercase": bool(re.search(r"[a-z]", raw)),
        "has_digit": bool(re.search(r"\d", raw)),
        "has_special": bool(re.search(r"[^A-Za-z0-9\s]", raw)),
    }
    score = sum(1 for passed in checks.values() if passed)
    missing = []
    if not checks["min_length"]:
        missing.append("at least 8 characters")
    if not checks["has_uppercase"]:
        missing.append("an uppercase letter (A-Z)")
    if not checks["has_lowercase"]:
        missing.append("a lowercase letter (a-z)")
    if not checks["has_digit"]:
        missing.append("a number (0-9)")
    if not checks["has_special"]:
        missing.append("a special character (e.g. !@#$%^&*)")

    return {
        "is_strong": score == 5,
        "score": score,
        "checks": checks,
        "missing": missing,
    }


def compute_bmi(height_cm: Optional[float], weight_kg: Optional[float]) -> Dict[str, Any]:
    """Calculate BMI and category if both height and weight are positive."""
    if not height_cm or not weight_kg or height_cm <= 0 or weight_kg <= 0:
        return {"bmi": None, "bmi_category": None}
    height_m = height_cm / 100.0
    bmi_val = round(weight_kg / (height_m * height_m), 1)
    if bmi_val < 18.5:
        category = "Underweight"
    elif bmi_val < 25.0:
        category = "Normal weight"
    elif bmi_val < 30.0:
        category = "Overweight"
    else:
        category = "Obesity"
    return {"bmi": bmi_val, "bmi_category": category}


ALLOWED_AVATAR_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def get_profile_picture_url(profile: Optional[UserProfile]) -> str:
    """Return the API URL to serve the user's stored profile picture file, or empty string."""
    if profile is not None and profile.profile_picture and getattr(profile.profile_picture, "name", ""):
        return f"/api/profile/avatar/{profile.owner_id}"
    return ""


def get_profile_avatar(owner_id: str) -> FileResponse:
    """Serve a user's stored profile picture from MEDIA_ROOT / object storage."""
    try:
        owner_uuid = uuid.UUID(str(owner_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid owner_id.") from exc

    profile = UserProfile.objects.filter(owner_id=owner_uuid).first()
    if profile is None or not profile.profile_picture or not getattr(profile.profile_picture, "name", ""):
        raise HttpError(404, "Profile picture not found.")

    content_type = profile.profile_picture_content_type or "image/png"
    if content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        content_type = "application/octet-stream"

    response = FileResponse(profile.profile_picture.open("rb"), content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    return response


def serialize_user_profile(user) -> Dict[str, Any]:
    """Serialize a User and their UserProfile into a dictionary."""
    profile = ensure_user_profile(user)
    bmi_info = compute_bmi(profile.height_cm, profile.weight_kg)
    allergies_list = [
        item.strip()
        for item in re.split(r"[,;\n]+", profile.allergies or "")
        if item.strip()
    ]
    avatar = get_profile_picture_url(profile)
    base_data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "owner_id": str(profile.owner_id),
        "name": profile.name or user.username,
        "age": profile.age,
        "height_cm": profile.height_cm,
        "height": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "weight": profile.weight_kg,
        "gender": profile.gender or "",
        "allergies": profile.allergies or "",
        "allergies_list": allergies_list,
        "bio": profile.bio or "",
        "profile_picture": avatar,
        "avatar_url": avatar,
        "profile_picture_name": profile.profile_picture_name or "",
        "has_profile_picture": bool(avatar),
        "bmi": bmi_info["bmi"],
        "bmi_category": bmi_info["bmi_category"],
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    result = dict(base_data)
    result["profile"] = dict(base_data)
    result["user"] = dict(base_data, profile=dict(base_data))
    return result


def signup_user(
    *,
    username: str,
    email: str,
    password: str,
    name: str = "",
    owner_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new user account and initialize their UserProfile."""
    clean_username = (username or "").strip()
    clean_email = (email or "").strip().lower()
    raw_password = password or ""

    if not clean_username or not clean_email or not raw_password:
        raise HttpError(400, "Username, email, and password are required.")

    if len(clean_username) < 3:
        raise HttpError(400, "Username must be at least 3 characters long.")

    if len(clean_username) > 150:
        raise HttpError(400, "Username must be 150 characters or fewer.")

    if not re.match(r"^[A-Za-z0-9_.\-@+]+$", clean_username):
        raise HttpError(
            400,
            "Username may only contain letters, numbers, and @/./+/-/_ characters.",
        )

    if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HttpError(400, "Please provide a valid email address.")

    pw_eval = validate_password_strength(raw_password)
    if not pw_eval["is_strong"]:
        missing_str = ", ".join(pw_eval["missing"])
        raise HttpError(
            400,
            f"Please choose a stronger password. Missing: {missing_str}.",
        )

    if User.objects.filter(username__iexact=clean_username).exists():
        raise HttpError(400, "That username is already taken. Please choose another.")

    if User.objects.filter(email__iexact=clean_email).exists():
        raise HttpError(400, "An account with that email address already exists.")

    with transaction.atomic():
        existing_guest_profile = None
        if owner_id:
            try:
                owner_uuid = uuid.UUID(str(owner_id))
                cand = UserProfile.objects.select_related("user").filter(owner_id=owner_uuid).first()
                if cand and cand.user.username.startswith("guest_"):
                    existing_guest_profile = cand
            except (ValueError, TypeError):
                pass

        if existing_guest_profile is not None:
            user = existing_guest_profile.user
            user.username = clean_username
            user.email = clean_email
            user.set_password(raw_password)
            user.save()
            profile = existing_guest_profile
        else:
            user = User.objects.create_user(
                username=clean_username,
                email=clean_email,
                password=raw_password,
            )
            profile = ensure_user_profile(user, preferred_owner_id=owner_id)

        if name and name.strip():
            profile.name = name.strip()[:150]
            profile.save(update_fields=["name", "updated_at"])

    token = create_auth_token(user)
    return {
        "status": "ok",
        "token": token,
        "user": serialize_user_profile(user),
    }


def login_user(*, username_or_email: str, password: str) -> Dict[str, Any]:
    """Authenticate an existing user by username or email and password."""
    identifier = (username_or_email or "").strip()
    raw_password = password or ""

    if not identifier or not raw_password:
        raise HttpError(400, "Username (or email) and password are required.")

    target_user = (
        User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        )
        .first()
    )
    if target_user is None:
        raise HttpError(401, "Invalid username/email or password.")

    authenticated = authenticate(username=target_user.username, password=raw_password)
    if authenticated is None:
        raise HttpError(401, "Invalid username/email or password.")

    token = create_auth_token(authenticated)
    return {
        "status": "ok",
        "token": token,
        "user": serialize_user_profile(authenticated),
    }


def _save_profile_picture_bytes(
    profile: UserProfile,
    image_bytes: bytes,
    *,
    filename: str = "",
    content_type: str = "image/png",
) -> None:
    """Save profile picture bytes to MEDIA_ROOT/user_profiles/avatars/%Y/%m/%d/ via FileField."""
    clean_type = (content_type or "image/png").split(";")[0].strip().lower()
    if clean_type == "image/jpg":
        clean_type = "image/jpeg"
    if clean_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise HttpError(400, "Unsupported profile image format. Allowed: JPEG, PNG, WEBP, GIF.")
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HttpError(400, "Profile picture exceeds maximum size of 5 MB.")

    ext = ALLOWED_AVATAR_CONTENT_TYPES[clean_type]
    safe_name = Path((filename or "").replace("\\", "/")).name
    if not safe_name or "." not in safe_name:
        safe_name = f"avatar_{profile.owner_id}{ext}"

    if profile.profile_picture and getattr(profile.profile_picture, "name", ""):
        profile.profile_picture.delete(save=False)

    profile.profile_picture_name = safe_name[:255]
    profile.profile_picture_content_type = clean_type
    profile.profile_picture.save(safe_name, ContentFile(image_bytes), save=False)


def update_user_profile(
    user,
    *,
    name: Optional[str] = None,
    age: Optional[Any] = None,
    height_cm: Optional[Any] = None,
    weight_kg: Optional[Any] = None,
    gender: Optional[str] = None,
    allergies: Optional[str] = None,
    bio: Optional[str] = None,
    email: Optional[str] = None,
    profile_picture: Optional[str] = None,
    profile_picture_data: Optional[bytes] = None,
    profile_picture_name: str = "",
    profile_picture_content_type: str = "",
) -> Dict[str, Any]:
    """Update a user's profile fields with validation and store profile images in MEDIA_ROOT."""
    profile = ensure_user_profile(user)

    if email is not None and email.strip():
        clean_email = email.strip().lower()
        if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
            raise HttpError(400, "Please provide a valid email address.")
        if User.objects.filter(email__iexact=clean_email).exclude(pk=user.pk).exists():
            raise HttpError(400, "That email is already associated with another account.")
        user.email = clean_email
        user.save(update_fields=["email"])

    if name is not None:
        profile.name = name.strip()[:150]

    if age is not None:
        if str(age).strip() == "":
            profile.age = None
        else:
            try:
                parsed_age = int(float(str(age).strip()))
            except (ValueError, TypeError) as exc:
                raise HttpError(400, "Age must be a valid whole number.") from exc
            if parsed_age < 1 or parsed_age > 130:
                raise HttpError(400, "Age must be between 1 and 130.")
            profile.age = parsed_age

    if height_cm is not None:
        if str(height_cm).strip() == "":
            profile.height_cm = None
        else:
            try:
                parsed_height = round(float(str(height_cm).strip()), 1)
            except (ValueError, TypeError) as exc:
                raise HttpError(400, "Height must be a valid number in cm.") from exc
            if parsed_height < 30 or parsed_height > 300:
                raise HttpError(400, "Height must be between 30 cm and 300 cm.")
            profile.height_cm = parsed_height

    if weight_kg is not None:
        if str(weight_kg).strip() == "":
            profile.weight_kg = None
        else:
            try:
                parsed_weight = round(float(str(weight_kg).strip()), 1)
            except (ValueError, TypeError) as exc:
                raise HttpError(400, "Weight must be a valid number in kg.") from exc
            if parsed_weight < 2 or parsed_weight > 500:
                raise HttpError(400, "Weight must be between 2 kg and 500 kg.")
            profile.weight_kg = parsed_weight

    if gender is not None:
        profile.gender = gender.strip()[:32]

    if allergies is not None:
        profile.allergies = allergies.strip()[:2000]

    if bio is not None:
        profile.bio = bio.strip()[:3000]

    if profile_picture_data is not None:
        _save_profile_picture_bytes(
            profile,
            profile_picture_data,
            filename=profile_picture_name,
            content_type=profile_picture_content_type or "image/png",
        )
    elif profile_picture is not None:
        clean_pic = profile_picture.strip()
        if not clean_pic:
            if profile.profile_picture and getattr(profile.profile_picture, "name", ""):
                profile.profile_picture.delete(save=False)
            profile.profile_picture = ""
            profile.profile_picture_name = ""
            profile.profile_picture_content_type = ""
        elif clean_pic.startswith("data:image/"):
            match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", clean_pic, flags=re.DOTALL)
            if not match:
                raise HttpError(400, "Invalid profile image data.")
            mime_type = match.group(1).lower()
            try:
                decoded_bytes = base64.b64decode(match.group(2))
            except Exception as exc:
                raise HttpError(400, "Invalid base64 profile image payload.") from exc
            _save_profile_picture_bytes(
                profile,
                decoded_bytes,
                filename=profile_picture_name,
                content_type=mime_type,
            )
        elif (
            clean_pic.startswith("/api/profile/avatar/")
            or clean_pic.startswith("/media/")
            or clean_pic.startswith("/profile-assets/")
        ):
            # Existing stored avatar URL echoed back by the client; keep current file unchanged
            pass
        else:
            raise HttpError(400, "Profile picture must be an uploaded image file.")

    profile.save()
    return serialize_user_profile(user)


def build_profile_context_for_ai(owner_id: Optional[str] = None, user=None) -> str:
    """Return a concise summary of a user's profile (allergies, biometrics) for meal planning."""
    profile = None
    if user is not None:
        profile = ensure_user_profile(user)
    elif owner_id:
        try:
            owner_uuid = uuid.UUID(str(owner_id))
            profile = UserProfile.objects.filter(owner_id=owner_uuid).first()
        except (ValueError, TypeError):
            profile = None

    if profile is None:
        return ""

    parts = []
    if profile.name:
        parts.append(f"Name: {profile.name}")
    if profile.age:
        parts.append(f"Age: {profile.age}")
    if profile.gender:
        parts.append(f"Gender: {profile.gender}")
    if profile.height_cm:
        parts.append(f"Height: {profile.height_cm} cm")
    if profile.weight_kg:
        parts.append(f"Weight: {profile.weight_kg} kg")
    if profile.allergies:
        parts.append(f"CRITICAL ALLERGIES TO AVOID: {profile.allergies}")
    if profile.bio:
        parts.append(f"Bio/Context: {profile.bio}")
    return " | ".join(parts)


# ─── Groups & Collective Nutrition Tracking ──────────────────────────────────


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

    # 1. Group-specific meal logs
    group_logs = GroupMealLog.objects.filter(group=group, user=member_user).order_by("-created_at")
    for log in group_logs:
        totals["meals_count"] += 1
        totals["calories_kcal"] += float(log.calories_kcal or 0.0)
        totals["protein_g"] += float(log.protein_g or 0.0)
        totals["carbohydrates_g"] += float(log.carbohydrates_g or 0.0)
        totals["total_fat_g"] += float(log.total_fat_g or 0.0)
        totals["dietary_fiber_g"] += float(log.dietary_fiber_g or 0.0)
        recent_meals.append({
            "id": str(log.id),
            "source": "group_log",
            "username": member_user.username,
            "member_name": profile.name or member_user.username,
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

        totals["meals_count"] += 1
        totals["calories_kcal"] += cals
        totals["protein_g"] += prot
        totals["carbohydrates_g"] += carbs
        totals["total_fat_g"] += fat
        totals["dietary_fiber_g"] += fiber

        recent_meals.append({
            "id": str(tm.id),
            "source": "tracked_meal",
            "username": member_user.username,
            "member_name": profile.name or member_user.username,
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

    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "is_public": group.is_public,
        "visibility": "public" if group.is_public else "private",
        "created_by": group.created_by.username,
        "member_count": len(memberships),
        "is_member": is_member,
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
        "collective_nutrition": collective,
        "members": members_data,
        "member_breakdown": members_data,
        "recent_meals": all_recent_meals[:5],
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
        my_qs = NutritionGroup.objects.filter(id__in=my_group_ids).select_related("created_by")
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
