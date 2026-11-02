import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ChatConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
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
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.conversation}: {self.user_query[:60]}"


class MealPlanHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=160)
    preferences = models.JSONField(default=list)
    custom_request = models.TextField(blank=True)
    plan = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner_id", "-created_at"])]

    def __str__(self):
        return self.title


class UserProfile(models.Model):
    """
    Extended user profile storing personal, biometric, and dietary details.
    Stored in the core_app database alongside chat history and meal plans.
    Profile images are stored as files under MEDIA_ROOT ('user_profiles/avatars/%Y/%m/%d/')
    so that MEDIA_ROOT / Django STORAGES['default'] can seamlessly point to object storage in production.
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
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile of {self.user.username}"


class NutritionGroup(models.Model):
    """
    User-created group (public or private) for tracking collective nutrition across members.
    Public group names must be unique. Stored in the core_app database.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, db_index=True)
    description = models.TextField(blank=True, default="")
    is_public = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True for public group (unique name required), False for private group",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_nutrition_groups",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Nutrition Group"
        verbose_name_plural = "Nutrition Groups"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(is_public=True),
                name="unique_public_nutrition_group_name",
            )
        ]

    def __str__(self):
        visibility = "Public" if self.is_public else "Private"
        return f"{self.name} ({visibility})"


class GroupMembership(models.Model):
    """
    Membership linking users to a NutritionGroup in the core_app database.
    """
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_MEMBER, "Member"),
    ]

    group = models.ForeignKey(
        NutritionGroup,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="nutrition_group_memberships",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="added_group_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("group", "user")]
        ordering = ["joined_at"]
        verbose_name = "Group Membership"
        verbose_name_plural = "Group Memberships"

    def __str__(self):
        return f"{self.user.username} in {self.group.name} ({self.role})"


class GroupMealLog(models.Model):
    """
    Meal nutrition entry logged to a group by a member for collective nutrition tracking.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        NutritionGroup,
        on_delete=models.CASCADE,
        related_name="meal_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="group_meal_logs",
    )
    meal_title = models.CharField(max_length=200)
    meal_type = models.CharField(max_length=32, default="Meal")
    calories_kcal = models.FloatField(default=0.0)
    protein_g = models.FloatField(default=0.0)
    carbohydrates_g = models.FloatField(default=0.0)
    total_fat_g = models.FloatField(default=0.0)
    dietary_fiber_g = models.FloatField(default=0.0)
    serving_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Group Meal Log"
        verbose_name_plural = "Group Meal Logs"

    def __str__(self):
        return f"{self.meal_title} ({self.calories_kcal} kcal) by {self.user.username}"


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
        ordering = ["-consumed_at", "-created_at"]
        verbose_name = "Tracked Meal"
        verbose_name_plural = "Tracked Meals"
        indexes = [
            models.Index(fields=["owner_id", "-consumed_at"]),
        ]

    def __str__(self):
        cals = (self.macronutrients or {}).get("calories_kcal", 0)
        return f"{self.meal_title} ({cals} kcal) [{self.owner_id}]"


class GroupMembershipRequest(models.Model):
    """
    Two-way invitation and join request system:
    - Invitation: Group admin requests a user to join. User has ownership to accept or reject.
    - Join Request: User requests to join a group. Group admin has ownership to accept or reject.
    """
    TYPE_INVITATION = "invitation"
    TYPE_JOIN_REQUEST = "join_request"
    TYPE_CHOICES = [
        (TYPE_INVITATION, "Invitation"),
        (TYPE_JOIN_REQUEST, "Join Request"),
    ]

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        NutritionGroup,
        on_delete=models.CASCADE,
        related_name="membership_requests",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="group_membership_requests",
        help_text="Target user receiving the invitation or user requesting to join",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_group_requests",
        help_text="Admin who sent the invitation or user who initiated the join request",
    )
    request_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_JOIN_REQUEST,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responded_group_requests",
    )
    message = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Group Membership Request"
        verbose_name_plural = "Group Membership Requests"
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["group", "status"]),
            models.Index(fields=["request_type", "status"]),
        ]

    def __str__(self):
        return f"{self.request_type.capitalize()} for {self.user.username} in {self.group.name} [{self.status}]"
