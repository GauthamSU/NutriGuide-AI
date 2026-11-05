import uuid
from django.db import models


class ChatConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        app_label = "chat_history"
        db_table = "chat_history_chatconversation"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner_id", "-updated_at"])]

    def __str__(self):
        return self.title


class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        ChatConversation, on_delete=models.CASCADE, related_name="messages"
    )
    user_query = models.TextField(blank=True)
    transcription = models.TextField(blank=True)
    input_modalities = models.JSONField(default=list)
    ai_response = models.JSONField(default=dict)
    image = models.FileField(
        upload_to="chat_history/images/%Y/%m/%d/", blank=True
    )
    image_name = models.CharField(max_length=255, blank=True)
    image_content_type = models.CharField(max_length=100, blank=True)
    audio = models.FileField(
        upload_to="chat_history/audio/%Y/%m/%d/", blank=True
    )
    audio_name = models.CharField(max_length=255, blank=True)
    audio_content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "chat_history"
        db_table = "chat_history_chatmessage"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.conversation}: {self.user_query[:60]}"


class UserCustomRecipe(models.Model):
    """
    Stores household-customized recipes and ingredient modifications made by users.
    Enables personalized nutrient tracking (e.g., swapping mustard oil for coconut oil or ghee,
    adjusting portions) and powers dataset curation for model fine-tuning and recommendation engines.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        "auth.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="custom_recipes",
    )
    dish_name = models.CharField(max_length=255, db_index=True, help_text="User customized dish name / title")
    description = models.TextField(blank=True, default="", help_text="User customized dish description / summary")
    ai_dish_name = models.CharField(max_length=255, blank=True, default="", help_text="Original baseline AI suggested dish name")
    ai_description = models.TextField(blank=True, default="", help_text="Original baseline AI suggested dish description / recognized input summary")
    conversation_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    message_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    original_ingredients = models.JSONField(
        default=list,
        blank=True,
        help_text="Original baseline ingredients identified before household customization",
    )
    customized_ingredients = models.JSONField(
        default=list,
        help_text="User customized ingredients with names, weights in grams, and portions",
    )

    total_macronutrients = models.JSONField(
        default=dict,
        blank=True,
        help_text="Recalculated total macronutrients grounded in IFCT reference database",
    )
    total_micronutrients = models.JSONField(
        default=dict,
        blank=True,
        help_text="Recalculated total micronutrients (vitamins and minerals)",
    )

    notes = models.TextField(
        blank=True,
        default="",
        help_text="Household recipe notes or modification description (e.g., coconut oil used)",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        app_label = "chat_history"
        db_table = "chat_history_usercustomrecipe"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner_id", "dish_name"]),
            models.Index(fields=["owner_id", "-updated_at"]),
            models.Index(fields=["owner_id", "message_id"]),
        ]
        verbose_name = "User Custom Recipe"
        verbose_name_plural = "User Custom Recipes"

    def __str__(self):
        return f"{self.dish_name} ({self.owner_id})"

