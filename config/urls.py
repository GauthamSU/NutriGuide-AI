from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI
from nutrition.api import (
    auth_router,
    groups_router,
    profile_router,
    router as nutrition_router,
    tracker_router,
)
from chat_history.api import router as chat_history_router

api = NinjaAPI(
    title="NutriGuide-AI API",
    version="0.1.0",
    description=(
        "Multimodal (Text, Image, Voice) Food Nutrient Analysis API powered by "
        "Django Ninja, LangGraph, and local Gemma 4 via llama.cpp."
    ),
)

api.add_router("/nutrition", nutrition_router)
api.add_router("/chat-history", chat_history_router)
api.add_router("/auth", auth_router)
api.add_router("/profile", profile_router)
api.add_router("/groups", groups_router)
api.add_router("/tracker", tracker_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

