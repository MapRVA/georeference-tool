import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0059_alter_collection_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectionEmbeddingStats",
            fields=[
                (
                    "collection",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="embedding_stats",
                        serialize=False,
                        to="images.collection",
                    ),
                ),
                (
                    "mean_embedding",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.FloatField(),
                        help_text="Mean of the collection's searchable image embeddings (not unit-length)",
                        size=None,
                    ),
                ),
                (
                    "embedding_count",
                    models.PositiveIntegerField(
                        help_text="Number of embeddings averaged into mean_embedding"
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name_plural": "collection embedding stats",
            },
        ),
    ]
