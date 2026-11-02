from django.contrib import admin

from chat_history.models import (
    ChatConversation,
    ChatMessage,
    GroupMealLog,
    GroupMembership,
    GroupMembershipRequest,
    MealPlanHistory,
    NutritionGroup,
    TrackedMeal,
    UserProfile,
)


class CoreAppReadOnlyAdmin(admin.ModelAdmin):
    using = "default"

    def get_queryset(self, request):
        return super().get_queryset(request).using(self.using)

    def has_module_permission(self, request):
        return request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


ChatHistoryReadOnlyAdmin = CoreAppReadOnlyAdmin


@admin.register(ChatConversation)
class ChatConversationAdmin(CoreAppReadOnlyAdmin):
    list_display = ("title", "owner_id", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at")
    search_fields = ("title", "owner_id")
    readonly_fields = ("id", "owner_id", "title", "created_at", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(CoreAppReadOnlyAdmin):
    list_display = (
        "conversation",
        "user_query",
        "input_modalities",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("user_query", "transcription", "conversation__title")
    readonly_fields = (
        "id",
        "conversation",
        "user_query",
        "transcription",
        "input_modalities",
        "ai_response",
        "image",
        "image_name",
        "image_content_type",
        "audio",
        "audio_name",
        "audio_content_type",
        "created_at",
    )


@admin.register(MealPlanHistory)
class MealPlanHistoryAdmin(CoreAppReadOnlyAdmin):
    list_display = ("title", "owner_id", "created_at")
    list_filter = ("created_at",)
    search_fields = ("title", "owner_id", "custom_request")
    readonly_fields = (
        "id",
        "owner_id",
        "title",
        "preferences",
        "custom_request",
        "plan",
        "created_at",
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "age", "height_cm", "weight_kg", "gender", "owner_id", "updated_at")
    search_fields = ("user__username", "user__email", "name", "allergies")


@admin.register(NutritionGroup)
class NutritionGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "is_public", "created_by", "created_at")
    list_filter = ("is_public",)
    search_fields = ("name", "description", "created_by__username")


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("group", "user", "role", "joined_at")
    list_filter = ("role",)
    search_fields = ("group__name", "user__username")


@admin.register(GroupMealLog)
class GroupMealLogAdmin(admin.ModelAdmin):
    list_display = ("meal_title", "group", "user", "meal_type", "calories_kcal", "protein_g", "created_at")
    list_filter = ("meal_type",)
    search_fields = ("meal_title", "group__name", "user__username")


@admin.register(TrackedMeal)
class TrackedMealAdmin(admin.ModelAdmin):
    list_display = ("meal_title", "owner_id", "user", "meal_type", "logged_via", "created_at")
    list_filter = ("meal_type", "logged_via", "created_at")
    search_fields = ("meal_title", "owner_id", "user__username")


@admin.register(GroupMembershipRequest)
class GroupMembershipRequestAdmin(admin.ModelAdmin):
    list_display = ("group", "user", "created_by", "request_type", "status", "created_at")
    list_filter = ("request_type", "status", "created_at")
    search_fields = ("group__name", "user__username", "created_by__username")
