import base64
import json
import logging
import mimetypes
import os
import time
import uuid
from email import policy
from email.parser import BytesParser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from web_frontend.urls import FRAGMENT_ROUTES, PAGE_ROUTES
except ImportError:
    from urls import FRAGMENT_ROUTES, PAGE_ROUTES


FRONTEND_ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("nutriguide.frontend")
logging.basicConfig(
    level=os.getenv("FRONTEND_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
TEMPLATES = Environment(
    loader=FileSystemLoader(FRONTEND_ROOT / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)
with (FRONTEND_ROOT / "config.json").open(encoding="utf-8") as config_file:
    FRONTEND_CONFIG = json.load(config_file)
API_BASE_URL = os.getenv(
    "API_BASE_URL", FRONTEND_CONFIG.get("api_base_url", "http://127.0.0.1:8000")
).rstrip("/")


def _empty_tracker_summary() -> dict:
    empty_macros = {
        "calories_kcal": 0.0,
        "protein_g": 0.0,
        "carbohydrates_g": 0.0,
        "dietary_fiber_g": 0.0,
        "total_sugars_g": 0.0,
        "added_sugars_g": 0.0,
        "total_fat_g": 0.0,
        "saturated_fat_g": 0.0,
        "monounsaturated_fat_g": 0.0,
        "polyunsaturated_fat_g": 0.0,
        "unsaturated_fat_g": 0.0,
        "trans_fat_g": 0.0,
        "cholesterol_mg": 0.0,
        "sodium_mg": 0.0,
        "water_g": 0.0,
    }
    empty_period = {
        "period": "daily",
        "label": "Daily Tracker (Today)",
        "period_label": "Daily Tracker (Today)",
        "period_days": 1,
        "meals_count": 0,
        "active_days": 0,
        "daily_average_calories_kcal": 0.0,
        "macronutrients": dict(empty_macros),
        "total_macronutrients": dict(empty_macros),
        "daily_average_macronutrients": dict(empty_macros),
        "macro_target_percents": {k: 0.0 for k in empty_macros},
        "micronutrients": {"vitamins": [], "minerals": []},
        "total_micronutrients": {"vitamins": [], "minerals": []},
        "meals": [],
    }
    return {
        "active_period": "daily",
        **empty_period,
        "periods": {
            "daily": {**empty_period, "period": "daily", "label": "Daily Tracker (Today)", "period_label": "Daily Tracker (Today)", "period_days": 1},
            "weekly": {**empty_period, "period": "weekly", "label": "Weekly Tracker (Last 7 Days)", "period_label": "Weekly Tracker (Last 7 Days)", "period_days": 7},
            "monthly": {**empty_period, "period": "monthly", "label": "Monthly Tracker (Last 30 Days)", "period_label": "Monthly Tracker (Last 30 Days)", "period_days": 30},
        },
    }


def build_page_context(current_path: str = "/", **extra) -> dict:
    """Build a standalone page context dictionary for template rendering."""
    context = {
        "api_base_url": API_BASE_URL,
        "owner_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "history": [],
        "meal_plan_history": [],
        "my_groups": [],
        "public_groups": [],
        "tracker_summary": _empty_tracker_summary(),
        "current_path": current_path,
        "current_user": None,
        "auth_mode": "signup" if current_path == "/signup" else "login",
    }
    context.update(extra)
    return context


def render_template(template_name: str, context: dict | None = None) -> str:
    """Render a Jinja2 template from the web_frontend templates directory."""
    return TEMPLATES.get_template(template_name).render(**(context or {}))



class FrontendHandler(BaseHTTPRequestHandler):
    server_version = "NutriGuideFrontend/1.0"

    def _auth_headers(self, token: str | None = None) -> dict:
        resolved = token if token is not None else self._get_auth_token()
        return {"Authorization": f"Bearer {resolved}"} if resolved else {}

    def do_GET(self):
        parsed_url = urlsplit(self.path)
        route_path = parsed_url.path.rstrip("/") or "/"
        query_params = parse_qs(parsed_url.query)

        # Support GET /logout or /auth/logout gracefully
        if route_path in {"/logout", "/auth/logout"}:
            self.clear_auth_cookie = True
            self.owner_cookie_value = str(uuid.uuid4())
            self._send_redirect("/login", status=303)
            return

        # Security: Immediately strip any sensitive or session parameters from browser URLs
        sensitive_query_keys = {"password", "identifier", "username", "username_or_email", "token", "owner_id"}
        if parsed_url.query and (
            any(k in sensitive_query_keys for k in query_params)
            or route_path in {"/login", "/signup", "/auth", "/"}
        ):
            self._send_redirect(route_path, status=302)
            return

        if route_path == "/meal-plans/history":
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        f"{API_BASE_URL}/api/chat-history/meal-plans",
                        params={"owner_id": owner_id},
                        headers=self._auth_headers(token),
                    )
                response.raise_for_status()
                self._send_json(response.json())
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load meal plan history")
                self._send_json(
                    {"detail": "Meal plan history is temporarily unavailable."},
                    status=502,
                )
            return

        if route_path == "/groups/data":
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            params = {"owner_id": owner_id}
            if query_params.get("q"):
                params["q"] = query_params["q"][-1]
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        f"{API_BASE_URL}/api/groups",
                        params=params,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load groups directory")
                self._send_json(
                    {"detail": "Groups directory is temporarily unavailable."},
                    status=502,
                )
            return

        if route_path == "/groups/notifications":
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            params = {"owner_id": owner_id}
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        f"{API_BASE_URL}/api/groups/notifications",
                        params=params,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load group notifications")
                self._send_json(
                    {"detail": "Could not load group notifications."},
                    status=502,
                )
            return

        if route_path == "/tracker/data":
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            period = (query_params.get("period") or ["daily"])[-1]
            params = {"owner_id": owner_id, "period": period}
            if query_params.get("date"):
                params["date"] = query_params["date"][-1]
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        f"{API_BASE_URL}/api/tracker/summary",
                        params=params,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load tracker summary")
                self._send_json(
                    {"detail": "Nutrient tracker is temporarily unavailable."},
                    status=502,
                )
            return

        if route_path.startswith("/groups/") and route_path.endswith("/data"):
            group_id = route_path.removeprefix("/groups/").removesuffix("/data").strip("/")
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            params = {"owner_id": owner_id}
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        f"{API_BASE_URL}/api/groups/{group_id}",
                        params=params,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load group detail group_id=%s", group_id)
                self._send_json(
                    {"detail": "Could not load group details."},
                    status=502,
                )
            return

        template_name = PAGE_ROUTES.get(route_path)
        if template_name:
            owner_id = self._get_owner_id()
            conversation_id = str(uuid.uuid4())
            context = self._page_context(
                owner_id,
                conversation_id,
                current_path=route_path,
            )
            if self.headers.get("HX-Request", "").lower() == "true":
                fragment = FRAGMENT_ROUTES.get(route_path, "components/chat_view.html")
                self._send_template(fragment, context)
            else:
                self._send_template(template_name, context)
        elif route_path.startswith("/chats/"):
            owner_id = self._get_owner_id()
            conversation_id = route_path.removeprefix("/chats/")
            context = self._page_context(owner_id, conversation_id)
            effective_owner = context.get("owner_id") or owner_id
            try:
                with httpx.Client(timeout=30.0) as client:
                    chat_params = {"owner_id": effective_owner}
                    token = self._get_auth_token()
                    if token:
                        chat_params["token"] = token
                    response = client.get(
                        f"{API_BASE_URL}/api/chat-history/conversations/{conversation_id}",
                        params=chat_params,
                    )
                response.raise_for_status()
                conversation = response.json()
                for message in conversation.get("messages", []):
                    analysis = message["result"].get("analysis") or {}
                    analysis["total_micronutrients"] = self._aggregate_micronutrients(
                        analysis.get("items") or []
                    )
                    message["result"]["analysis"] = analysis
                    if message.get("has_image"):
                        message["image_url"] = (
                            f"/chat-assets/{conversation_id}/{message['id']}/image"
                        )
                    if message.get("has_audio"):
                        message["audio_url"] = (
                            f"/chat-assets/{conversation_id}/{message['id']}/audio"
                        )
                context["conversation"] = conversation
                context["conversation_id"] = conversation_id
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load chat history conversation=%s", conversation_id)
                context["history_error"] = "Could not load this chat. Please try again."
            template = (
                "components/chat_view.html"
                if self.headers.get("HX-Request", "").lower() == "true"
                else "pages/analyze.html"
            )
            self._send_template(template, context)
        elif route_path.startswith("/groups/") and route_path != "/groups" and not route_path.endswith("/data"):
            owner_id = self._get_owner_id()
            token = self._get_auth_token()
            group_id = route_path.removeprefix("/groups/").strip("/")
            context = self._page_context(owner_id, conversation_id=str(uuid.uuid4()), current_path=route_path)
            context["current_group_id"] = str(group_id)
            try:
                with httpx.Client(timeout=30.0) as client:
                    g_params = {"owner_id": owner_id}
                    if token:
                        g_params["token"] = token
                    response = client.get(
                        f"{API_BASE_URL}/api/groups/{group_id}",
                        params=g_params,
                    )
                if response.is_success:
                    g_data = response.json() or {}
                    if "collective_nutrition" in g_data and "collective" not in g_data:
                        g_data["collective"] = g_data["collective_nutrition"]
                    context["group"] = g_data
                else:
                    context["group_error"] = (response.json() or {}).get("detail", "Could not load this group.")
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load group page group_id=%s", group_id)
                context["group_error"] = "Could not load this group. Please try again."

            template = (
                "components/group_detail_view.html"
                if self.headers.get("HX-Request", "").lower() == "true"
                else "pages/group_detail.html"
            )
            self._send_template(template, context)
        elif route_path.startswith("/chat-assets/"):
            self._send_chat_asset(route_path)
        elif route_path.startswith("/api/profile/avatar/") or route_path.startswith("/profile-assets/"):
            self._send_profile_avatar(route_path)
        elif route_path.startswith("/media/"):
            self._send_media_file(route_path)
        elif route_path == "/analyze/loading":
            self._send_template("components/loading_turn.html", {})
        elif route_path in {"/favicon.ico", "/favicon.svg"}:
            self._send_asset("/assets/medical-icon--nutrition.svg")
        elif route_path.startswith("/assets/"):
            self._send_asset(route_path)
        elif route_path.startswith("/src/"):
            self._send_asset(route_path)
        elif route_path in {"/pyscript.json", "/pyscript.toml"}:
            self._send_asset(f"/src{route_path}")
        elif route_path.endswith(".py"):
            self._send_asset(f"/src/{route_path.split('/')[-1]}")
        else:
            self._send_template("pages/error.html", {"message": "Page not found."}, status=404)

    def do_POST(self):
        route_path = urlsplit(self.path).path.rstrip("/") or "/"
        accept_header = self.headers.get("Accept", "").lower()
        wants_json = "application/json" in accept_header

        # ─── Authentication Proxy Routes ──────────────────────────────────────
        if route_path in {"/auth/signup", "/auth/login", "/login", "/signup"}:
            fields, _ = self._parse_form()
            owner_id = self._get_owner_id()
            fields.setdefault("owner_id", owner_id)
            if fields.get("identifier") and not fields.get("username_or_email"):
                fields["username_or_email"] = fields["identifier"]
            if fields.get("full_name") and not fields.get("name"):
                fields["name"] = fields["full_name"]

            is_signup = route_path in {"/auth/signup", "/signup"}
            api_endpoint = (
                f"{API_BASE_URL}/api/auth/signup"
                if is_signup
                else f"{API_BASE_URL}/api/auth/login"
            )
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(api_endpoint, json=fields)
                payload = response.json()
                if response.is_success:
                    if payload.get("token"):
                        self.auth_cookie_value = payload["token"]
                    user_owner_id = (payload.get("user") or {}).get("owner_id")
                    if user_owner_id:
                        self.owner_cookie_value = user_owner_id
                    if not wants_json:
                        self._send_redirect("/", status=303)
                        return
                elif not wants_json:
                    err_msg = (payload or {}).get("detail") or "Authentication failed. Please check your credentials."
                    context = self._page_context(
                        owner_id,
                        str(uuid.uuid4()),
                        current_path="/signup" if is_signup else "/login",
                        auth_error=str(err_msg),
                    )
                    self._send_template("pages/auth.html", context, status=response.status_code)
                    return
                self._send_json(payload, status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Authentication API request failed path=%s", route_path)
                if not wants_json:
                    context = self._page_context(
                        owner_id,
                        str(uuid.uuid4()),
                        current_path="/signup" if is_signup else "/login",
                        auth_error="Authentication service is temporarily unavailable.",
                    )
                    self._send_template("pages/auth.html", context, status=502)
                    return
                self._send_json(
                    {"detail": "Authentication service is temporarily unavailable."},
                    status=502,
                )
            return

        if route_path in {"/auth/logout", "/logout"}:
            self.clear_auth_cookie = True
            self.owner_cookie_value = str(uuid.uuid4())
            if not wants_json:
                self._send_redirect("/login", status=303)
                return
            self._send_json({"status": "ok"})
            return

        # ─── Open Chat Conversation via Clean POST (No UUID in URL) ───────────
        if route_path == "/chats/open":
            fields, _ = self._parse_form()
            conversation_id = str(fields.get("conversation_id") or "").strip()
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            context = self._page_context(owner_id, conversation_id or str(uuid.uuid4()), current_path="/")
            effective_owner = context.get("owner_id") or owner_id
            if conversation_id:
                try:
                    with httpx.Client(timeout=30.0) as client:
                        response = client.get(
                            f"{API_BASE_URL}/api/chat-history/conversations/{conversation_id}",
                            params={"owner_id": effective_owner},
                            headers=self._auth_headers(token),
                        )
                    response.raise_for_status()
                    conversation = response.json()
                    for message in conversation.get("messages", []):
                        analysis = message["result"].get("analysis") or {}
                        analysis["total_micronutrients"] = self._aggregate_micronutrients(
                            analysis.get("items") or []
                        )
                        message["result"]["analysis"] = analysis
                        if message.get("has_image"):
                            message["image_url"] = f"/chat-assets/{conversation_id}/{message['id']}/image"
                        if message.get("has_audio"):
                            message["audio_url"] = f"/chat-assets/{conversation_id}/{message['id']}/audio"
                    context["conversation"] = conversation
                    context["conversation_id"] = conversation_id
                except (httpx.HTTPError, ValueError):
                    logger.exception("Could not load chat history conversation=%s", conversation_id)
                    context["history_error"] = "Could not load this chat. Please try again."
            template = (
                "components/chat_view.html"
                if self.headers.get("HX-Request", "").lower() == "true"
                else "pages/analyze.html"
            )
            self._send_template(template, context)
            return

        # ─── Open Group Detail via Clean POST (No UUID in URL) ────────────────
        if route_path == "/groups/open":
            fields, _ = self._parse_form()
            group_id = str(fields.get("group_id") or "").strip()
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            context = self._page_context(owner_id, conversation_id=str(uuid.uuid4()), current_path="/groups")
            context["current_group_id"] = group_id
            if group_id:
                try:
                    with httpx.Client(timeout=30.0) as client:
                        response = client.get(
                            f"{API_BASE_URL}/api/groups/{group_id}",
                            params={"owner_id": owner_id},
                            headers=self._auth_headers(token),
                        )
                    if response.is_success:
                        g_data = response.json() or {}
                        if "collective_nutrition" in g_data and "collective" not in g_data:
                            g_data["collective"] = g_data["collective_nutrition"]
                        context["group"] = g_data
                    else:
                        context["group_error"] = (response.json() or {}).get("detail", "Could not load this group.")
                except (httpx.HTTPError, ValueError):
                    logger.exception("Could not load group page group_id=%s", group_id)
                    context["group_error"] = "Could not load this group. Please try again."
            template = (
                "components/group_detail_view.html"
                if self.headers.get("HX-Request", "").lower() == "true"
                else "pages/group_detail.html"
            )
            self._send_template(template, context)
            return

        # ─── Profile Update Proxy Route ───────────────────────────────────────
        if route_path in {"/profile/update", "/profile/upload", "/api/profile/upload", "/api/profile"}:
            fields, uploads = self._parse_form()
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            fields["owner_id"] = owner_id
            if token:
                fields["token"] = token
            avatar_upload = None
            for field_name, filename, content_type, data in uploads:
                if field_name in {"avatar", "profile_picture_file", "profile_picture"} and data:
                    guessed_mime, _ = mimetypes.guess_type(filename or "")
                    mime = content_type or guessed_mime or "image/png"
                    avatar_upload = (filename or "avatar.png", data, mime)
                    break
            api_headers = self._auth_headers(token)
            try:
                with httpx.Client(timeout=30.0) as client:
                    if avatar_upload is not None:
                        form_data = {k: str(v) for k, v in fields.items() if v is not None}
                        response = client.post(
                            f"{API_BASE_URL}/api/profile/upload",
                            data=form_data,
                            files=[("profile_picture_file", avatar_upload)],
                            headers=api_headers,
                        )
                    else:
                        if str(fields.get("remove_profile_picture") or "").lower() in {"1", "true", "yes"}:
                            fields["profile_picture"] = ""
                        response = client.post(
                            f"{API_BASE_URL}/api/profile",
                            json=fields,
                            headers=api_headers,
                        )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Profile update failed")
                self._send_json({"detail": "Could not update profile."}, status=502)
            return

        # ─── Tracker Proxy Routes ─────────────────────────────────────────────
        if route_path == "/tracker/data":
            fields, _ = self._parse_form()
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            period = str(fields.get("period") or "daily").strip() or "daily"
            params = {"owner_id": owner_id, "period": period}
            if fields.get("date"):
                params["date"] = str(fields["date"])
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        f"{API_BASE_URL}/api/tracker/summary",
                        params=params,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not load tracker summary")
                self._send_json(
                    {"detail": "Nutrient tracker is temporarily unavailable."},
                    status=502,
                )
            return

        if route_path == "/tracker/log":
            fields, _ = self._parse_form()
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            fields["owner_id"] = owner_id
            if token:
                fields["token"] = token
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/tracker/log",
                        json=fields,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Tracker log request failed")
                self._send_json({"detail": "Could not log meal to tracker."}, status=502)
            return

        if route_path == "/tracker/meals/delete" or (
            route_path.startswith("/tracker/meals/") and route_path.endswith("/delete")
        ):
            fields, _ = self._parse_form()
            log_id = (
                str(fields.get("log_id") or "").strip()
                if route_path == "/tracker/meals/delete"
                else route_path.removeprefix("/tracker/meals/").removesuffix("/delete").strip("/")
            )
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/tracker/meals/{log_id}/delete",
                        params={"owner_id": owner_id},
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Tracker meal delete failed")
                self._send_json({"detail": "Could not remove meal from tracker."}, status=502)
            return

        # ─── Deletion Proxy Routes (Meal Plans, Conversations, Chat Messages) ─
        if route_path == "/meal-plans/delete" or (
            route_path.startswith("/meal-plans/") and route_path.endswith("/delete")
        ):
            fields, _ = self._parse_form()
            meal_plan_id = (
                str(fields.get("plan_id") or fields.get("meal_plan_id") or "").strip()
                if route_path == "/meal-plans/delete"
                else route_path.removeprefix("/meal-plans/").removesuffix("/delete").strip("/")
            )
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/chat-history/meal-plans/{meal_plan_id}/delete",
                        params={"owner_id": owner_id},
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not delete meal plan id=%s", meal_plan_id)
                self._send_json({"detail": "Could not delete meal plan."}, status=502)
            return

        if route_path in {"/chats/delete", "/chats/messages/delete"} or (
            route_path.startswith("/chats/") and route_path.endswith("/delete")
        ):
            fields, _ = self._parse_form()
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            conv_id = str(fields.get("conversation_id") or "").strip()
            msg_id = str(fields.get("message_id") or "").strip()
            if route_path not in {"/chats/delete", "/chats/messages/delete"}:
                inner = route_path.removeprefix("/chats/").removesuffix("/delete").strip("/")
                parts = [p for p in inner.split("/") if p]
                if len(parts) == 3 and parts[1] == "messages":
                    conv_id, _, msg_id = parts
                elif len(parts) == 2 and parts[0] == "messages":
                    msg_id = parts[1]
                elif len(parts) == 1:
                    conv_id = parts[0]

            try:
                with httpx.Client(timeout=30.0) as client:
                    if msg_id and conv_id:
                        response = client.post(
                            f"{API_BASE_URL}/api/chat-history/conversations/{conv_id}/messages/{msg_id}/delete",
                            params={"owner_id": owner_id},
                            headers=self._auth_headers(token),
                        )
                    elif msg_id:
                        response = client.post(
                            f"{API_BASE_URL}/api/chat-history/messages/{msg_id}/delete",
                            params={"owner_id": owner_id},
                            headers=self._auth_headers(token),
                        )
                    elif conv_id:
                        response = client.post(
                            f"{API_BASE_URL}/api/chat-history/conversations/{conv_id}/delete",
                            params={"owner_id": owner_id},
                            headers=self._auth_headers(token),
                        )
                    else:
                        self._send_json({"detail": "Invalid delete route."}, status=400)
                        return
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Chat deletion failed path=%s", route_path)
                self._send_json({"detail": "Could not delete chat item."}, status=502)
            return

        # ─── Recipe Customization Proxy Routes ────────────────────────────────
        if route_path.endswith("/customize-recipe"):
            inner = route_path.removeprefix("/chats/").removesuffix("/customize-recipe").strip("/")
            parts = [p for p in inner.split("/") if p]
            conv_id = parts[0] if len(parts) >= 3 and parts[1] == "messages" else (parts[0] if len(parts) == 2 and parts[0] != "messages" else "")
            msg_id = parts[-1] if parts and parts[-1] != "messages" else ""
            owner_id = self._get_effective_owner_id()
            fields, _ = self._parse_form()

            if not msg_id or msg_id == "messages":
                msg_id = str(fields.get("message_id") or "").strip()
            if not conv_id or conv_id == "messages":
                conv_id = str(fields.get("conversation_id") or "").strip()

            # Parse ingredients from JSON string or list
            raw_ingredients = fields.get("ingredients")
            if not raw_ingredients and "ingredients_json" in fields:
                try:
                    import json
                    raw_ingredients = json.loads(fields["ingredients_json"])
                except Exception:
                    raw_ingredients = []
            if not isinstance(raw_ingredients, list):
                raw_ingredients = []

            dish_name = fields.get("dish_name")
            description = fields.get("description") or fields.get("dish_description")
            notes = fields.get("notes") or ""
            api_payload = {
                "owner_id": owner_id,
                "dish_name": dish_name,
                "description": description,
                "notes": notes,
                "ingredients": [
                    {
                        "food_name": str(item.get("food_name") or item.get("ingredient_name") or "").strip(),
                        "estimated_weight_grams": float(item.get("estimated_weight_grams") or 0.0),
                        "serving_size_description": str(item.get("serving_size_description") or "1 serving"),
                    }
                    for item in raw_ingredients
                    if isinstance(item, dict) and str(item.get("food_name") or item.get("ingredient_name") or "").strip()
                ],
            }

            try:
                with httpx.Client(timeout=30.0) as client:
                    if conv_id and msg_id:
                        endpoint = f"{API_BASE_URL}/api/chat-history/conversations/{conv_id}/messages/{msg_id}/customize-recipe"
                    else:
                        endpoint = f"{API_BASE_URL}/api/chat-history/messages/{msg_id}/customize-recipe"
                    response = client.post(endpoint, json=api_payload)
                response.raise_for_status()
                data = response.json()

                is_html_req = (
                    self.headers.get("HX-Request", "").lower() == "true"
                    or "text/html" in self.headers.get("Accept", "").lower()
                )
                if is_html_req:
                    analysis = data.get("analysis") or {}
                    analysis["total_micronutrients"] = self._aggregate_micronutrients(
                        analysis.get("items") or []
                    )
                    turn_context = {
                        "result": {
                            "dish_name": data.get("dish_name") or dish_name,
                            "description": data.get("description") or description,
                            "ai_dish_name": data.get("ai_dish_name"),
                            "ai_description": data.get("ai_description"),
                            "analysis": analysis,
                            "dietary_warnings": data.get("warnings") or [],
                            "logged_to_tracker": data.get("logged_to_tracker"),
                            "tracker_log_id": data.get("tracker_log_id"),
                            "is_customized": True,
                        },
                        "turn_id": msg_id,
                        "conversation_id": conv_id,
                        "logged_to_tracker": data.get("logged_to_tracker"),
                    }
                    html = TEMPLATES.get_template("components/nutrition_results.html").render(**turn_context)
                    self._send_html(html)
                    return
                self._send_json(data, status=200)
            except Exception as exc:
                logger.exception("Recipe customization failed: %s", exc)
                self._send_json({"detail": "Could not customize recipe."}, status=502)
            return

        if route_path.endswith("/reset-recipe"):
            inner = route_path.removeprefix("/chats/").removesuffix("/reset-recipe").strip("/")
            parts = [p for p in inner.split("/") if p]
            conv_id = parts[0] if len(parts) >= 3 and parts[1] == "messages" else (parts[0] if len(parts) == 2 and parts[0] != "messages" else "")
            msg_id = parts[-1] if parts and parts[-1] != "messages" else ""
            owner_id = self._get_effective_owner_id()
            fields, _ = self._parse_form()
            if not msg_id or msg_id == "messages":
                msg_id = str(fields.get("message_id") or "").strip()
            if not conv_id or conv_id == "messages":
                conv_id = str(fields.get("conversation_id") or "").strip()
            try:
                with httpx.Client(timeout=30.0) as client:
                    if conv_id and msg_id:
                        endpoint = f"{API_BASE_URL}/api/chat-history/conversations/{conv_id}/messages/{msg_id}/reset-recipe"
                    else:
                        endpoint = f"{API_BASE_URL}/api/chat-history/messages/{msg_id}/reset-recipe"
                    response = client.post(endpoint, params={"owner_id": owner_id})
                response.raise_for_status()
                data = response.json()

                is_html_req = (
                    self.headers.get("HX-Request", "").lower() == "true"
                    or "text/html" in self.headers.get("Accept", "").lower()
                )
                if is_html_req:
                    analysis = data.get("analysis") or {}
                    analysis["total_micronutrients"] = self._aggregate_micronutrients(
                        analysis.get("items") or []
                    )
                    turn_context = {
                        "result": {
                            "dish_name": data.get("dish_name"),
                            "description": data.get("description"),
                            "ai_dish_name": data.get("ai_dish_name"),
                            "ai_description": data.get("ai_description"),
                            "analysis": analysis,
                            "dietary_warnings": data.get("warnings") or [],
                            "logged_to_tracker": data.get("logged_to_tracker"),
                            "tracker_log_id": data.get("tracker_log_id"),
                            "is_customized": False,
                        },
                        "turn_id": msg_id,
                        "conversation_id": conv_id,
                        "logged_to_tracker": data.get("logged_to_tracker"),
                    }
                    html = TEMPLATES.get_template("components/nutrition_results.html").render(**turn_context)
                    self._send_html(html)
                    return
                self._send_json(data, status=200)
            except Exception as exc:
                logger.exception("Recipe reset failed: %s", exc)
                self._send_json({"detail": "Could not reset recipe."}, status=502)
            return

        # ─── Groups Proxy Routes ──────────────────────────────────────────────
        if route_path == "/groups/create":
            fields, _ = self._parse_form()
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            fields["owner_id"] = owner_id
            if token:
                fields["token"] = token
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/groups",
                        json=fields,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Group creation failed")
                self._send_json({"detail": "Could not create group."}, status=502)
            return

        if route_path == "/groups/members" or (
            route_path.startswith("/groups/") and route_path.endswith("/members")
        ):
            fields, _ = self._parse_form()
            group_id = (
                str(fields.get("group_id") or "").strip()
                if route_path == "/groups/members"
                else route_path.removeprefix("/groups/").removesuffix("/members").strip("/")
            )
            fields["owner_id"] = self._get_effective_owner_id()
            token = self._get_auth_token()
            if token:
                fields["token"] = token
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/groups/{group_id}/members",
                        json=fields,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Group member add failed")
                self._send_json({"detail": "Could not add member to group."}, status=502)
            return

        if route_path == "/groups/join" or (
            route_path.startswith("/groups/") and route_path.endswith("/join")
        ):
            fields, _ = self._parse_form()
            group_id = (
                str(fields.get("group_id") or "").strip()
                if route_path == "/groups/join"
                else route_path.removeprefix("/groups/").removesuffix("/join").strip("/")
            )
            params = {"owner_id": self._get_effective_owner_id()}
            token = self._get_auth_token()
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/groups/{group_id}/join",
                        params=params,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Group join failed")
                self._send_json({"detail": "Could not join group."}, status=502)
            return

        if route_path == "/groups/meals" or (
            route_path.startswith("/groups/") and route_path.endswith("/meals")
        ):
            fields, uploads = self._parse_form()
            group_id = (
                str(fields.get("group_id") or "").strip()
                if route_path == "/groups/meals"
                else route_path.removeprefix("/groups/").removesuffix("/meals").strip("/")
            )
            owner_id = self._get_effective_owner_id()
            token = self._get_auth_token()
            fields["owner_id"] = owner_id
            if token:
                fields["token"] = token
            meal_text = (fields.get("meal_title") or fields.get("text") or "").strip()

            # If user uploaded photos or voice notes, analyze them with the multimodal AI endpoint
            if uploads:
                try:
                    data = {"text": meal_text, "owner_id": owner_id}
                    files = [
                        (field, (name, content, content_type))
                        for field, name, content_type, content in uploads
                    ]
                    with httpx.Client(timeout=60.0) as client:
                        ai_resp = client.post(
                            f"{API_BASE_URL}/api/nutrition/analyze",
                            data=data,
                            files=files,
                            headers=self._auth_headers(token),
                        )
                    if ai_resp.is_success:
                        ai_data = ai_resp.json() or {}
                        analysis = ai_data.get("analysis") or {}
                        macros = analysis.get("total_macronutrients") or {}
                        resolved_title = analysis.get("meal_title") or ai_data.get("transcription") or meal_text or "Shared Meal"
                        fields["meal_title"] = resolved_title
                        if macros.get("calories_kcal") is not None:
                            fields["calories_kcal"] = macros.get("calories_kcal")
                        if macros.get("protein_g") is not None:
                            fields["protein_g"] = macros.get("protein_g")
                        if macros.get("carbohydrates_g") is not None:
                            fields["carbohydrates_g"] = macros.get("carbohydrates_g")
                        if macros.get("total_fat_g") is not None:
                            fields["total_fat_g"] = macros.get("total_fat_g")
                        if macros.get("dietary_fiber_g") is not None:
                            fields["dietary_fiber_g"] = macros.get("dietary_fiber_g")
                        summary = analysis.get("recognized_input_summary") or ""
                        if summary:
                            fields["serving_notes"] = summary
                except Exception:
                    logger.exception("AI multimodal analysis before group meal post failed")
            elif meal_text and ("calories_kcal" not in fields or not fields.get("calories_kcal")):
                # Pure text input: query AI text analyze endpoint so portions and food items are parsed
                try:
                    with httpx.Client(timeout=25.0) as client:
                        ai_text_resp = client.post(
                            f"{API_BASE_URL}/api/nutrition/analyze/text",
                            json={"text": meal_text, "owner_id": owner_id},
                            headers=self._auth_headers(token),
                        )
                    if ai_text_resp.is_success:
                        ai_data = ai_text_resp.json() or {}
                        analysis = ai_data.get("analysis") or {}
                        macros = analysis.get("total_macronutrients") or {}
                        if analysis.get("meal_title"):
                            fields["meal_title"] = analysis["meal_title"]
                        if macros.get("calories_kcal") is not None:
                            fields["calories_kcal"] = macros.get("calories_kcal")
                        if macros.get("protein_g") is not None:
                            fields["protein_g"] = macros.get("protein_g")
                        if macros.get("carbohydrates_g") is not None:
                            fields["carbohydrates_g"] = macros.get("carbohydrates_g")
                        if macros.get("total_fat_g") is not None:
                            fields["total_fat_g"] = macros.get("total_fat_g")
                        if macros.get("dietary_fiber_g") is not None:
                            fields["dietary_fiber_g"] = macros.get("dietary_fiber_g")
                        summary = analysis.get("recognized_input_summary") or ""
                        if summary:
                            fields["serving_notes"] = summary
                except Exception:
                    logger.warning("AI text analysis fallback to IFCT DB for group meal")

            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/groups/{group_id}/meals",
                        json=fields,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Group meal log failed")
                self._send_json({"detail": "Could not log meal to group."}, status=502)
            return

        if route_path == "/groups/requests/respond" or (
            route_path.startswith("/groups/requests/") and route_path.endswith("/respond")
        ):
            fields, _ = self._parse_form()
            request_id = (
                str(fields.get("request_id") or "").strip()
                if route_path == "/groups/requests/respond"
                else route_path.removeprefix("/groups/requests/").removesuffix("/respond").strip("/")
            )
            fields["owner_id"] = self._get_effective_owner_id()
            token = self._get_auth_token()
            if token:
                fields["token"] = token
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/groups/requests/{request_id}/respond",
                        json=fields,
                        headers=self._auth_headers(token),
                    )
                self._send_json(response.json(), status=response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.exception("Group request response failed request_id=%s", request_id)
                self._send_json(
                    {"detail": "Could not respond to group request."},
                    status=502,
                )
            return

        # ─── Meal Plan Generation (JSON or Multimodal Form) ───────────────────
        if route_path == "/meal-plans/generate":
            fields, uploads = self._parse_form()
            owner_id = self._get_effective_owner_id(create=True)
            if not fields and not uploads:
                self._send_json({"detail": "A valid meal plan request is required."}, status=400)
                return

            prefs = fields.get("preferences", [])
            if isinstance(prefs, str):
                try:
                    prefs = json.loads(prefs)
                except ValueError:
                    prefs = [p.strip() for p in prefs.split(",") if p.strip()]

            json_payload = {
                "owner_id": owner_id,
                "preferences": prefs if isinstance(prefs, list) else [],
                "custom_request": str(fields.get("custom_request") or ""),
                "duration": str(fields.get("duration") or "daily"),
                "diet_type": str(fields.get("diet_type") or ""),
            }
            if fields.get("image_base64"):
                json_payload["image_base64"] = fields["image_base64"]
                json_payload["image_mime_type"] = fields.get("image_mime_type") or "image/jpeg"
            if fields.get("audio_base64"):
                json_payload["audio_base64"] = fields["audio_base64"]
                json_payload["audio_format"] = fields.get("audio_format") or "wav"

            for field_name, filename, content_type, data in uploads:
                if not data:
                    continue
                if field_name == "image":
                    json_payload["image_base64"] = base64.b64encode(data).decode("utf-8")
                    guessed_mime, _ = mimetypes.guess_type(filename or "")
                    json_payload["image_mime_type"] = content_type or guessed_mime or "image/jpeg"
                    json_payload["image_name"] = filename
                elif field_name == "voice":
                    json_payload["audio_base64"] = base64.b64encode(data).decode("utf-8")
                    ext = Path(filename or "audio.wav").suffix.lower().lstrip(".")
                    json_payload["audio_format"] = ext if ext in {"wav", "mp3"} else "wav"
                    json_payload["audio_name"] = filename

            try:
                with httpx.Client(timeout=600.0) as client:
                    response = client.post(
                        f"{API_BASE_URL}/api/nutrition/meal-plans/generate",
                        json=json_payload,
                        headers=self._auth_headers(),
                    )
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"detail": response.text or "The API returned an empty response."}
                self._send_json(payload, status=response.status_code)
            except httpx.HTTPError:
                logger.exception("Meal plan API request failed")
                self._send_json(
                    {"detail": "Could not reach the meal planning API. Please try again."},
                    status=502,
                )
            return

        if route_path not in {"/analyze", "/analyze/fragment", "/api/analyze"}:
            self._send_template("pages/error.html", {"message": "Page not found."}, status=404)
            return

        started = time.perf_counter()
        fields, uploads = self._parse_form()
        meal_text = fields.get("text", "").strip()
        effective_owner = self._get_effective_owner_id(create=True)
        fields["owner_id"] = effective_owner
        file_summary = [
            {"field": field, "filename": name, "content_type": content_type, "bytes": len(data)}
            for field, name, content_type, data in uploads
        ]
        logger.info(
            "Browser request method=%s path=%s client=%s text=%r uploads=%s",
            self.command,
            route_path,
            self.client_address[0],
            meal_text[:500],
            file_summary,
        )

        if not meal_text and not uploads:
            self._send_turn_fragment(
                user_text=meal_text,
                error="Add a meal description, photo, or voice note to continue.",
            )
            return

        if uploads:
            endpoint = f"{API_BASE_URL}/api/nutrition/analyze"
            data = {key: value for key, value in fields.items() if key != "text" or value}
            if meal_text:
                data["text"] = meal_text
            for key in ("owner_id", "conversation_id", "user_id"):
                if fields.get(key):
                    data[key] = fields[key]
            files = [
                (field, (name, content, content_type))
                for field, name, content_type, content in uploads
            ]
            request_description = {"form_fields": data, "uploads": file_summary}
        else:
            endpoint = f"{API_BASE_URL}/api/nutrition/analyze/text"
            data = {"text": meal_text}
            for key in ("user_id", "owner_id", "conversation_id"):
                if fields.get(key):
                    data[key] = fields[key]
            files = None
            request_description = data

        logger.info("Forwarding API request method=POST url=%s payload=%s", endpoint, request_description)
        try:
            with httpx.Client(timeout=360.0) as client:
                if files:
                    api_response = client.post(endpoint, data=data, files=files)
                else:
                    api_response = client.post(endpoint, json=data)
            duration_ms = round((time.perf_counter() - started) * 1000)
            response_text = api_response.text
            logger.info(
                "API response status=%s duration_ms=%s content_type=%s body_excerpt=%r",
                api_response.status_code,
                duration_ms,
                api_response.headers.get("content-type", ""),
                response_text[:2000],
            )
            try:
                api_payload = api_response.json()
            except ValueError:
                api_payload = {"detail": response_text[:2000] or "The API returned an empty response."}

            if api_response.is_success:
                analysis = api_payload.get("analysis") or {}
                api_payload["analysis"] = analysis
                analysis["total_micronutrients"] = self._aggregate_micronutrients(
                    analysis.get("items") or []
                )
                self._send_turn_fragment(
                    user_text=meal_text,
                    image_name=next((name for field, name, *_ in uploads if field == "image"), None),
                    voice_name=next((name for field, name, *_ in uploads if field == "voice"), None),
                    result=api_payload,
                    history_owner_id=fields.get("owner_id"),
                    selected_chat_id=fields.get("conversation_id"),
                )
            else:
                messages = api_payload.get("errors") or [api_payload.get("detail", "Analysis failed.")]
                error = " ".join(str(message) for message in messages)
                self._send_turn_fragment(
                    user_text=meal_text,
                    image_name=next((name for field, name, *_ in uploads if field == "image"), None),
                    voice_name=next((name for field, name, *_ in uploads if field == "voice"), None),
                    error=error,
                )
        except httpx.HTTPError:
            logger.exception("API request failed url=%s", endpoint)
            self._send_turn_fragment(
                user_text=meal_text,
                error=f"Could not reach the nutrition API at {API_BASE_URL}.",
            )

    def log_message(self, format_string, *args):
        import re as _re
        msg = format_string % args
        msg = _re.sub(r"([?&](?:password|identifier|token)=)[^&\s\"]+", r"\1[REDACTED]", msg, flags=_re.IGNORECASE)
        logger.info("HTTP %s - %s", self.client_address[0], msg)

    def _parse_form(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}, []
            return (parsed, []) if isinstance(parsed, dict) else ({}, [])
        if content_type.startswith("application/x-www-form-urlencoded"):
            parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
            return {key: values[-1] for key, values in parsed.items()}, []

        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        fields = {}
        uploads = []
        if not message.is_multipart():
            return fields, uploads
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not field_name:
                continue
            content = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                uploads.append((field_name, Path(filename).name, part.get_content_type(), content))
            else:
                charset = part.get_content_charset() or "utf-8"
                fields[field_name] = content.decode(charset, errors="replace")
        return fields, uploads

    def _get_cookies(self) -> SimpleCookie:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            logger.warning("Ignoring malformed cookie header")
        return cookie

    def _get_auth_token(self):
        cookie = self._get_cookies()
        token_morsel = cookie.get("nutriguide_token")
        return token_morsel.value if token_morsel and token_morsel.value else None

    def _get_owner_id(self, create=True):
        cookie = self._get_cookies()
        owner_cookie = cookie.get("nutriguide_owner")
        if owner_cookie:
            try:
                return str(uuid.UUID(owner_cookie.value))
            except ValueError:
                logger.warning("Ignoring invalid chat owner cookie")

        if not create:
            return None
        owner_id = str(uuid.uuid4())
        self.owner_cookie_value = owner_id
        return owner_id

    def _get_effective_owner_id(self, create=True):
        token = self._get_auth_token()
        owner_id = self._get_owner_id(create=create)
        if token:
            try:
                with httpx.Client(timeout=5.0) as client:
                    me_resp = client.get(
                        f"{API_BASE_URL}/api/auth/me",
                        headers=self._auth_headers(token),
                    )
                if me_resp.is_success:
                    user_data = (me_resp.json() or {}).get("user")
                    if user_data and not str(user_data.get("username", "")).startswith("guest_"):
                        if user_data.get("owner_id"):
                            owner_id = str(user_data["owner_id"])
                            self.owner_cookie_value = owner_id
                elif me_resp.status_code == 401:
                    self.clear_auth_cookie = True
                    owner_id = str(uuid.uuid4())
                    self.owner_cookie_value = owner_id
            except (httpx.HTTPError, ValueError):
                pass
        return owner_id

    def _page_context(self, owner_id, conversation_id=None, **context):
        conversation_id = conversation_id or str(uuid.uuid4())
        context.setdefault('current_path', getattr(self, 'path', '/').split('?')[0])
        health = None
        health_url = f"{API_BASE_URL}/api/nutrition/health"
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(health_url)
            if response.is_success:
                health = response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("API health request failed url=%s", health_url)

        current_user = None
        token = self._get_auth_token()
        if token:
            try:
                with httpx.Client(timeout=5.0) as client:
                    me_resp = client.get(
                        f"{API_BASE_URL}/api/auth/me",
                        headers=self._auth_headers(token),
                    )
                if me_resp.is_success:
                    user_data = (me_resp.json() or {}).get("user")
                    if user_data and not str(user_data.get("username", "")).startswith("guest_"):
                        current_user = user_data
                        if user_data.get("owner_id") and user_data["owner_id"] != owner_id:
                            owner_id = user_data["owner_id"]
                            self.owner_cookie_value = owner_id
                elif me_resp.status_code == 401:
                    self.clear_auth_cookie = True
                    owner_id = str(uuid.uuid4())
                    self.owner_cookie_value = owner_id
            except (httpx.HTTPError, ValueError):
                pass

        history_url = f"{API_BASE_URL}/api/chat-history/conversations"
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(history_url, params={"owner_id": owner_id})
            response.raise_for_status()
            chat_conversations = response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Chat history request failed url=%s", history_url)
            chat_conversations = []
            context.setdefault("history_error", "Chat history is temporarily unavailable.")

        my_groups = []
        public_groups = []
        pending_invitations = []
        admin_pending_requests = []
        my_pending_join_requests = []
        notifications_count = 0
        # Always prefetch groups so the collapsible sidebar list is populated across all pages
        if owner_id or token:
            try:
                g_params = {"owner_id": owner_id}
                with httpx.Client(timeout=10.0) as client:
                    g_resp = client.get(
                        f"{API_BASE_URL}/api/groups",
                        params=g_params,
                        headers=self._auth_headers(token),
                    )
                if g_resp.is_success:
                    g_data = g_resp.json() or {}
                    my_groups = g_data.get("my_groups") or []
                    public_groups = g_data.get("public_groups") or []
                    pending_invitations = g_data.get("pending_invitations") or []
                    admin_pending_requests = g_data.get("admin_pending_requests") or []
                    my_pending_join_requests = g_data.get("my_pending_join_requests") or []
                    notifications_count = g_data.get("notifications_count") or 0
            except (httpx.HTTPError, ValueError):
                logger.exception("Groups prefetch failed")

        tracker_summary = _empty_tracker_summary()
        if context.get("current_path") == "/tracker":
            try:
                t_params = {"owner_id": owner_id, "period": "daily"}
                with httpx.Client(timeout=10.0) as client:
                    t_resp = client.get(
                        f"{API_BASE_URL}/api/tracker/summary",
                        params=t_params,
                        headers=self._auth_headers(token),
                    )
                if t_resp.is_success:
                    tracker_summary = t_resp.json() or tracker_summary
            except (httpx.HTTPError, ValueError):
                logger.exception("Tracker prefetch failed")

        return {
            "api_base_url": API_BASE_URL,
            "health": health,
            "current_user": current_user,
            "owner_id": owner_id,
            "conversation_id": conversation_id,
            "chat_conversations": chat_conversations,
            "selected_chat_id": conversation_id,
            "my_groups": my_groups,
            "public_groups": public_groups,
            "pending_invitations": pending_invitations,
            "admin_pending_requests": admin_pending_requests,
            "my_pending_join_requests": my_pending_join_requests,
            "notifications_count": notifications_count,
            "tracker_summary": tracker_summary,
            **context,
        }

    def _send_turn_fragment(self, **context):
        context.setdefault(
            "include_user",
            self.headers.get("HX-Request", "").lower() != "true",
        )
        owner_id = context.pop("history_owner_id", None)
        selected_chat_id = context.pop("selected_chat_id", None)
        result_obj = context.get("result") or {}
        if isinstance(result_obj, dict):
            context.setdefault("turn_id", result_obj.get("message_id"))
            context.setdefault("logged_to_tracker", bool(result_obj.get("logged_to_tracker")))
        if selected_chat_id:
            context.setdefault("conversation_id", selected_chat_id)
        context["history_oob"] = False
        if owner_id:
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(
                        f"{API_BASE_URL}/api/chat-history/conversations",
                        params={"owner_id": owner_id},
                    )
                response.raise_for_status()
                context["chat_conversations"] = response.json()
                context["selected_chat_id"] = selected_chat_id
                context["history_oob"] = True
            except (httpx.HTTPError, ValueError):
                logger.exception("Could not refresh chat history sidebar")
        turn_html = TEMPLATES.get_template("components/conversation_turn.html").render(**context)
        self._send_html(turn_html)

    def _send_chat_asset(self, route_path):
        parts = route_path.strip("/").split("/")
        if len(parts) != 4:
            self.send_error(404)
            return
        owner_id = self._get_owner_id()
        _, conversation_id, message_id, kind = parts
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    f"{API_BASE_URL}/api/chat-history/conversations/"
                    f"{conversation_id}/messages/{message_id}/{kind}",
                    params={"owner_id": owner_id},
                )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Could not retrieve chat attachment")
            self.send_error(404)
            return
        body = response.content
        self.send_response(response.status_code)
        self.send_header(
            "Content-Type",
            response.headers.get("content-type", "application/octet-stream"),
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_profile_avatar(self, route_path):
        owner_id = route_path.rstrip("/").split("/")[-1]
        if not owner_id:
            self.send_error(404)
            return
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(f"{API_BASE_URL}/api/profile/avatar/{owner_id}")
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Could not retrieve profile avatar owner_id=%s", owner_id)
            self.send_error(404)
            return
        body = response.content
        self.send_response(response.status_code)
        self.send_header(
            "Content-Type",
            response.headers.get("content-type", "image/png"),
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self._safe_write(body)

    def _send_media_file(self, route_path):
        rel_path = route_path.removeprefix("/media/").lstrip("/")
        media_root = Path(os.getenv("CORE_APP_MEDIA_ROOT", str(FRONTEND_ROOT.parent / "media")))
        file_path = (media_root / rel_path).resolve()
        if not str(file_path).startswith(str(media_root.resolve())) or not file_path.is_file():
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(f"{API_BASE_URL}{route_path}")
                if resp.is_success:
                    self.send_response(resp.status_code)
                    self.send_header("Content-Type", resp.headers.get("content-type", "application/octet-stream"))
                    self.send_header("Content-Length", str(len(resp.content)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self._safe_write(resp.content)
                    return
            except Exception:
                pass
            self.send_error(404)
            return

        guessed_mime, _ = mimetypes.guess_type(file_path.name)
        content_type = guessed_mime or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self._safe_write(body)

    @staticmethod
    def _aggregate_micronutrients(items):
        totals = {"vitamins": {}, "minerals": {}}
        for item in items:
            micronutrients = item.get("micronutrients") or {}
            for category in totals:
                for nutrient in micronutrients.get(category) or []:
                    name = str(nutrient.get("name", "Unknown"))
                    unit = str(nutrient.get("unit", ""))
                    key = (name, unit)
                    aggregate = totals[category].setdefault(
                        key,
                        {"name": name, "unit": unit, "amount": 0.0, "daily_value_percent": 0.0},
                    )
                    aggregate["amount"] += float(nutrient.get("amount") or 0.0)
                    aggregate["daily_value_percent"] += float(nutrient.get("daily_value_percent") or 0.0)
        return {
            category: [
                {**nutrient, "amount": round(nutrient["amount"], 2), "daily_value_percent": round(nutrient["daily_value_percent"], 1)}
                for nutrient in category_totals.values()
            ]
            for category, category_totals in totals.items()
        }

    def _write_cookies(self):
        secure_suffix = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
        if getattr(self, "owner_cookie_value", None):
            cookie = (
                f"nutriguide_owner={self.owner_cookie_value}; Path=/; "
                f"Max-Age=31536000; HttpOnly; SameSite=Lax{secure_suffix}"
            )
            self.send_header("Set-Cookie", cookie)
        if getattr(self, "auth_cookie_value", None):
            auth_cookie = (
                f"nutriguide_token={self.auth_cookie_value}; Path=/; "
                f"Max-Age=2592000; HttpOnly; SameSite=Lax{secure_suffix}"
            )
            self.send_header("Set-Cookie", auth_cookie)
        if getattr(self, "clear_auth_cookie", False):
            clear_cookie = f"nutriguide_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{secure_suffix}"
            self.send_header("Set-Cookie", clear_cookie)

    def _safe_write(self, body: bytes):
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            logger.debug("Client closed connection before response completed")

    def _send_redirect(self, location: str, status: int = 303):
        try:
            self.send_response(status)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self._write_cookies()
            self.end_headers()
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def _send_template(self, template_name, context, status=200):
        ctx = dict(context or {})
        route_path = getattr(self, "path", "/").split("?")[0]
        ctx.setdefault("current_path", route_path)
        ctx.setdefault("my_groups", [])
        ctx.setdefault("public_groups", [])
        ctx.setdefault("chat_conversations", [])
        ctx.setdefault("current_user", None)
        ctx.setdefault("notifications_count", 0)
        body = TEMPLATES.get_template(template_name).render(**ctx).encode("utf-8")
        self._send_html(body.decode("utf-8"), status=status)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            # Cache-Control already sent above
            self._write_cookies()
            self.end_headers()
            self._safe_write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            # Cache-Control already sent above
            self._write_cookies()
            self.end_headers()
            self._safe_write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def _send_asset(self, route_path):
        asset_path = (FRONTEND_ROOT / route_path.lstrip("/")).resolve()
        if FRONTEND_ROOT not in asset_path.parents or not asset_path.is_file():
            self.send_error(404)
            return
        content_types = {
            ".css": "text/css; charset=utf-8",
            ".py": "text/plain; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".toml": "text/plain; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        content_type = content_types.get(asset_path.suffix, "application/octet-stream")
        body = asset_path.read_bytes()
        if asset_path.suffix == ".py":
            body = body.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.end_headers()
            self._safe_write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass


def main():
    host = os.getenv("FRONTEND_HOST", "127.0.0.1")
    port = int(os.getenv("FRONTEND_PORT", "5500"))
    server = ThreadingHTTPServer((host, port), FrontendHandler)
    logger.info("Frontend listening at http://%s:%s/; API origin=%s", host, port, API_BASE_URL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping frontend server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
