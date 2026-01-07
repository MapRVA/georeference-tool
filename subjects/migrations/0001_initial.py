import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        # Depend on the last images migration that has these models
        ("images", "0027_move_maplayer_and_layercollection_to_maps"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # Rename tables from images_* to subjects_*
                migrations.RunSQL(
                    sql="ALTER TABLE images_wikidataitem RENAME TO subjects_wikidataitem",
                    reverse_sql="ALTER TABLE subjects_wikidataitem RENAME TO images_wikidataitem",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE images_osmelement RENAME TO subjects_osmelement",
                    reverse_sql="ALTER TABLE subjects_osmelement RENAME TO images_osmelement",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE images_subject RENAME TO subjects_subject",
                    reverse_sql="ALTER TABLE subjects_subject RENAME TO images_subject",
                ),
            ],
            state_operations=[
                # Register models in subjects app state
                migrations.CreateModel(
                    name="WikidataItem",
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
                            "wikidata_id",
                            models.CharField(
                                help_text="Wikidata ID (e.g., Q123456)",
                                max_length=20,
                                unique=True,
                            ),
                        ),
                        (
                            "title",
                            models.CharField(
                                help_text="Title from Wikidata", max_length=500
                            ),
                        ),
                        (
                            "description",
                            models.TextField(
                                blank=True, help_text="Description from Wikidata"
                            ),
                        ),
                        (
                            "wikipedia_url",
                            models.URLField(
                                blank=True,
                                help_text="URL to Wikipedia page (if available)",
                            ),
                        ),
                        (
                            "va_landmark_id",
                            models.CharField(
                                blank=True,
                                help_text="Virginia Landmarks Registry ID",
                                max_length=30,
                            ),
                        ),
                        (
                            "architect",
                            models.TextField(
                                blank=True,
                                help_text="Architect(s) - multiple names can be separated by commas",
                            ),
                        ),
                        (
                            "image_url",
                            models.URLField(
                                blank=True,
                                help_text="URL to representative image from Wikidata",
                                max_length=500,
                            ),
                        ),
                        (
                            "inception",
                            models.DateField(
                                blank=True,
                                help_text="Date of construction/inception",
                                null=True,
                            ),
                        ),
                        (
                            "last_updated",
                            models.DateTimeField(
                                auto_now=True,
                                help_text="When metadata was last fetched from Wikidata",
                            ),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "ordering": ["title"],
                    },
                ),
                migrations.CreateModel(
                    name="OsmElement",
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
                            "osm_id",
                            models.BigIntegerField(
                                help_text="OpenStreetMap element ID", unique=True
                            ),
                        ),
                        (
                            "geometry",
                            django.contrib.gis.db.models.fields.GeometryField(
                                help_text="Geometry of the OSM element (point, polygon, multipolygon, etc.)",
                                srid=4326,
                            ),
                        ),
                        (
                            "geometry_area",
                            models.FloatField(
                                default=0,
                                help_text="Cached area of the geometry in square degrees (used for render ordering)",
                            ),
                        ),
                        (
                            "updated_at",
                            models.DateTimeField(
                                auto_now=True,
                                help_text="When this row was last updated",
                            ),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "ordering": ["osm_id"],
                    },
                ),
                migrations.CreateModel(
                    name="Subject",
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
                            "title",
                            models.CharField(
                                help_text="Name/title of the subject", max_length=500
                            ),
                        ),
                        ("slug", models.SlugField(unique=True)),
                        (
                            "description",
                            models.TextField(
                                help_text="Admin-written description of the subject"
                            ),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "osm_element",
                            models.ForeignKey(
                                blank=True,
                                help_text="Optional linked OpenStreetMap element",
                                null=True,
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="subjects",
                                to="subjects.osmelement",
                            ),
                        ),
                        (
                            "wikidata_item",
                            models.ForeignKey(
                                blank=True,
                                help_text="Optional linked Wikidata item",
                                null=True,
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="subjects",
                                to="subjects.wikidataitem",
                            ),
                        ),
                    ],
                    options={
                        "ordering": ["title"],
                    },
                ),
            ],
        ),
    ]
