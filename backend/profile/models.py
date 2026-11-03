import uuid
from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """
    Extended user profile storing personal, biometric, and dietary details.
    Stored in the core_app database alongside chat history and meal plans.
    """
    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
        ("non-binary", "Non-binary"),
        ("other", "Other"),
        ("prefer_not_to_say", "Prefer not to say"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    owner_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="UUID used to partition chat history and meal plans for this user",
    )
    name = models.CharField(max_length=150, blank=True, default="")
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    height_cm = models.FloatField(null=True, blank=True, help_text="Height in centimeters")
    weight_kg = models.FloatField(null=True, blank=True, help_text="Weight in kilograms")
    gender = models.CharField(max_length=32, blank=True, default="")
    allergies = models.TextField(blank=True, default="", help_text="Allergies and dietary intolerances")
    bio = models.TextField(blank=True, default="", help_text="General bio about the user")
    profile_picture = models.FileField(
        upload_to="user_profiles/avatars/%Y/%m/%d/",
        blank=True,
        help_text="Profile picture file stored in MEDIA_ROOT / object storage",
    )
    profile_picture_name = models.CharField(max_length=255, blank=True, default="")
    profile_picture_content_type = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "chat_history"
        db_table = "chat_history_userprofile"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile of {self.user.username}"
