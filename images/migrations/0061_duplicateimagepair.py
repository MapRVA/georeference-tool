import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0060_collectionembeddingstats"),
    ]

    operations = [
        migrations.CreateModel(
            name="DuplicateImagePair",
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
                    "distance",
                    models.FloatField(
                        help_text="Cosine distance between the two image embeddings (0 = identical)"
                    ),
                ),
                (
                    "computed_at",
                    models.DateTimeField(
                        help_text="When the nightly scan that produced this pair ran"
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
            ],
            options={
                "ordering": ["distance"],
                "unique_together": {("image_a", "image_b")},
            },
        ),
    ]
