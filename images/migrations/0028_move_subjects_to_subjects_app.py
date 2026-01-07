import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0027_move_maplayer_and_layercollection_to_maps"),
        ("subjects", "0001_initial"),
    ]

    operations = [
        # First, remove the models from images app state (no DB changes needed)
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                # Remove FKs from Subject first (required before deleting referenced models)
                migrations.RemoveField(
                    model_name="subject",
                    name="osm_element",
                ),
                migrations.RemoveField(
                    model_name="subject",
                    name="wikidata_item",
                ),
                # Now delete the models from images app state
                migrations.DeleteModel(
                    name="OsmElement",
                ),
                migrations.DeleteModel(
                    name="WikidataItem",
                ),
                migrations.DeleteModel(
                    name="Subject",
                ),
            ],
        ),
        # Update SubjectMapping FK to point to subjects.Subject
        migrations.AlterField(
            model_name="subjectmapping",
            name="subject",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="image_mappings",
                to="subjects.subject",
            ),
        ),
        # Update Image M2M to point to subjects.Subject
        migrations.AlterField(
            model_name="image",
            name="subjects",
            field=models.ManyToManyField(
                blank=True,
                help_text="Subjects (buildings, people, monuments, etc.) that appear in this image",
                through="images.SubjectMapping",
                to="subjects.subject",
            ),
        ),
    ]
