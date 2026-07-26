import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("images", "0061_duplicateimagepair"),
    ]

    operations = [
        migrations.CreateModel(
            name="DismissedDuplicatePair",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "image_a",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="images.image",
                    ),
                ),
                (
                    "image_b",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="images.image",
                    ),
                ),
                (
                    "dismissed_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="Staff member who dismissed the pair",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("dismissed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-dismissed_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="dismissedduplicatepair",
            constraint=models.UniqueConstraint(
                fields=("image_a", "image_b"), name="unique_dismissed_pair"
            ),
        ),
        migrations.AddConstraint(
            model_name="dismissedduplicatepair",
            constraint=models.CheckConstraint(
                condition=models.Q(("image_a__lt", models.F("image_b"))),
                name="dismissed_pair_canonical_order",
            ),
        ),
    ]
