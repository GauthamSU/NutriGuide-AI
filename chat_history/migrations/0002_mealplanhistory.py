import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat_history", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MealPlanHistory",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("owner_id", models.CharField(db_index=True, max_length=64)),
                ("title", models.CharField(max_length=160)),
                ("preferences", models.JSONField(default=list)),
                ("custom_request", models.TextField(blank=True)),
                ("plan", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["owner_id", "-created_at"],
                        name="chat_histor_owner_i_7eaee2_idx",
                    )
                ],
            },
        ),
    ]
