from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI
from nutrition.api import router as nutrition_router

api = NinjaAPI(
    title="NutriGuide-AI API",
    version="0.1.0",
    description=(
        "Multimodal (Text, Image, Voice) Food Nutrient Analysis API powered by "
        "Django Ninja, LangGraph, and local Gemma 4 via llama.cpp."
    ),
)

api.add_router("/nutrition", nutrition_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
