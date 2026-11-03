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

from backend.profile.models import UserProfile

User = get_user_model()
AUTH_TOKEN_SALT = 'nutriguide.auth.token'
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

    if owner_id:
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


