import uuid
from django.db import models


class MealPlanHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=160)
    preferences = models.JSONField(default=list)
    custom_request = models.TextField(blank=True)
    plan = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "chat_history"
        db_table = "chat_history_mealplanhistory"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner_id", "-created_at"])]

    def __str__(self):
        return self.title
