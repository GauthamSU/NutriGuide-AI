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
