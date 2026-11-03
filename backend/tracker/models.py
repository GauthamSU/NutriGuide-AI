import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class TrackedMeal(models.Model):
    """
    Individual meal entry explicitly logged into a user's personal Nutrient Tracker
    (either via explicit voice/text instruction during chat or via the 'Log to Tracker' button).
    Stores complete macronutrient and micronutrient profiles for Daily, Weekly, and Monthly aggregation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tracked_meals",
    )
    conversation_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="ChatConversation UUID if logged from a chat conversation turn",
    )
    source_message_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="ChatMessage UUID if logged from a chat conversation turn",
    )
    meal_title = models.CharField(max_length=255)
    meal_type = models.CharField(max_length=32, default="Meal")
    recognized_summary = models.TextField(blank=True, default="")
    macronutrients = models.JSONField(default=dict, blank=True)
    micronutrients = models.JSONField(default=dict, blank=True)
    items = models.JSONField(default=list, blank=True)
    logged_via = models.CharField(
        max_length=32,
        default="button",
        help_text="'button', 'chat_button', 'text_intent', 'voice_intent', or 'manual'",
    )
    consumed_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="Timestamp when the food/meal was consumed",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "chat_history"
        db_table = "chat_history_trackedmeal"
        ordering = ["-consumed_at", "-created_at"]
        verbose_name = "Tracked Meal"
        verbose_name_plural = "Tracked Meals"
        indexes = [
            models.Index(fields=["owner_id", "-consumed_at"]),
        ]

    def __str__(self):
        cals = (self.macronutrients or {}).get("calories_kcal", 0)
        return f"{self.meal_title} ({cals} kcal) [{self.owner_id}]"
