import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


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
        app_label = "chat_history"
        db_table = "chat_history_nutritiongroup"
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
        app_label = "chat_history"
        db_table = "chat_history_groupmembership"
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
        app_label = "chat_history"
        db_table = "chat_history_groupmeallog"
        ordering = ["-created_at"]
        verbose_name = "Group Meal Log"
        verbose_name_plural = "Group Meal Logs"

    def __str__(self):
        return f"{self.meal_title} ({self.calories_kcal} kcal) by {self.user.username}"


class GroupMembershipRequest(models.Model):
    """
    Model managing user invitations and join requests for nutrition groups.
    """
    TYPE_INVITATION = "invitation"
    TYPE_JOIN_REQUEST = "join_request"
    TYPE_CHOICES = [
        (TYPE_INVITATION, "Admin Invitation"),
        (TYPE_JOIN_REQUEST, "User Join Request"),
    ]

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
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
        app_label = "chat_history"
        db_table = "chat_history_groupmembershiprequest"
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
