import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0006_delete_pre_tracking_subject_introductions"),
        ("images", "0056_imageoftheday_note_html"),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectionIntroduction",
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
                    "created_at",
                    models.DateTimeField(
                        db_index=True, help_text="When the collection was announced"
                    ),
                ),
                (
                    "collection",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="introduction",
                        to="images.collection",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
