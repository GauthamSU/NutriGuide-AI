import mimetypes
from typing import Optional

from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile

from backend.common.schemas import (
    LoginRequestSchema,
    SignupRequestSchema,
    UserProfileUpdateSchema,
)
from backend.profile.services import (
    get_profile_avatar,
    get_user_from_request,
    login_user,
    serialize_user_profile,
    signup_user,
    update_user_profile,
)

auth_router = Router(tags=["Authentication"])
profile_router = Router(tags=["User Profile"])


# ─── Authentication Endpoints ─────────────────────────────────────────────────


@auth_router.post("/signup", summary="Create a new user account with username, email, and password")
def api_signup(request, payload: SignupRequestSchema):
    return signup_user(
        username=payload.username,
        email=payload.email,
        password=payload.password,
        name=payload.name or "",
        owner_id=payload.owner_id,
    )


@auth_router.post("/login", summary="Authenticate user with username/email and password")
def api_login(request, payload: LoginRequestSchema):
    identifier = (payload.username_or_email or payload.username or payload.email or "").strip()
    return login_user(username_or_email=identifier, password=payload.password)


@auth_router.post("/logout", summary="Log out the current user")
def api_logout(request):
    return {"status": "ok", "message": "Logged out successfully."}


@auth_router.get("/me", summary="Get the currently authenticated user and profile")
def api_me(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return {"user": serialize_user_profile(user)}


# ─── User Profile Endpoints ──────────────────────────────────────────────────


@profile_router.get("", summary="Retrieve user profile details")
def api_get_profile(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return serialize_user_profile(user)


@profile_router.put("", summary="Update user profile (name, age, height, weight, gender, allergies, bio)")
@profile_router.post("", summary="Update user profile (name, age, height, weight, gender, allergies, bio)")
def api_update_profile(request, payload: UserProfileUpdateSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    height_val = payload.height_cm if payload.height_cm is not None else payload.height
    weight_val = payload.weight_kg if payload.weight_kg is not None else payload.weight
    pic_val = payload.profile_picture if payload.profile_picture is not None else payload.avatar_url
    return update_user_profile(
        user,
        name=payload.name,
        age=payload.age,
        height_cm=height_val,
        weight_kg=weight_val,
        gender=payload.gender,
        allergies=payload.allergies,
        bio=payload.bio,
        email=payload.email,
        profile_picture=pic_val,
    )


@profile_router.post("/upload", summary="Update user profile with multipart file upload for profile picture")
def api_update_profile_upload(
    request,
    name: Optional[str] = Form(default=None),
    age: Optional[str] = Form(default=None),
    height_cm: Optional[str] = Form(default=None),
    height: Optional[str] = Form(default=None),
    weight_kg: Optional[str] = Form(default=None),
    weight: Optional[str] = Form(default=None),
    gender: Optional[str] = Form(default=None),
    allergies: Optional[str] = Form(default=None),
    bio: Optional[str] = Form(default=None),
    email: Optional[str] = Form(default=None),
    profile_picture: Optional[str] = Form(default=None),
    remove_profile_picture: Optional[str] = Form(default=None),
    owner_id: Optional[str] = Form(default=None),
    token: Optional[str] = Form(default=None),
    profile_picture_file: Optional[UploadedFile] = File(default=None),
):
    user = get_user_from_request(
        request,
        token=token,
        owner_id=owner_id,
        require_auth=True,
    )
    height_val = height_cm if height_cm is not None else height
    weight_val = weight_kg if weight_kg is not None else weight

    raw_avatar: Optional[bytes] = None
    avatar_name = ""
    avatar_content_type = ""
    if profile_picture_file is not None:
        raw_avatar = profile_picture_file.read()
        if not raw_avatar:
            raise HttpError(400, "Uploaded profile picture file is empty.")
        avatar_name = profile_picture_file.name or "avatar.png"
        guessed_mime, _ = mimetypes.guess_type(avatar_name)
        avatar_content_type = profile_picture_file.content_type or guessed_mime or "image/png"
    elif str(remove_profile_picture or "").strip().lower() in {"1", "true", "yes"}:
        profile_picture = ""

    return update_user_profile(
        user,
        name=name,
        age=age,
        height_cm=height_val,
        weight_kg=weight_val,
        gender=gender,
        allergies=allergies,
        bio=bio,
        email=email,
        profile_picture=profile_picture,
        profile_picture_data=raw_avatar,
        profile_picture_name=avatar_name,
        profile_picture_content_type=avatar_content_type,
    )


@profile_router.get("/avatar/{owner_id}", summary="Serve stored profile picture from MEDIA_ROOT / object storage")
def api_get_profile_avatar(request, owner_id: str):
    return get_profile_avatar(owner_id)
