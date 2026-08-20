import django.db.models.deletion
from django.contrib.gis.geos import Point
from django.db import migrations, models


RICHMOND_COORDINATE = Point(-77.4366667, 37.5408333, srid=4326)
IMAGE_OF_THE_DAY_REGION_HELP_TEXT = (
    "The region whose homepage features this image on this day."
)


def provision_legacy_region(apps, schema_editor):
    """Assign content from the former single-region site to Richmond.

    Fresh databases stay unseeded. On an upgrade from the last release,
    however, every existing source predates region support and therefore
    depicts the site's original Richmond coverage area unless an editor later
    narrows or overrides it at the collection or image level.
    """
    Source = apps.get_model("images", "Source")
    if not Source.objects.exists():
        return

    Region = apps.get_model("regions", "Region")
    WikidataItem = apps.get_model("subjects", "WikidataItem")
    wikidata_item, _ = WikidataItem.objects.get_or_create(
        wikidata_id="Q43421",
        defaults={"title": "Richmond"},
    )
    region, _ = Region.objects.get_or_create(
        wikidata_item=wikidata_item,
        defaults={
            "short_name": "Richmond",
            "long_name": "Richmond, Virginia",
            "slug": "richmond",
            "wikidata_coordinate_location": RICHMOND_COORDINATE,
        },
    )
    Source.objects.filter(region__isnull=True).update(region=region)


def backfill_image_of_the_day_regions(apps, schema_editor):
    """Resolve each legacy queue entry through image -> collection -> source."""
    ImageOfTheDay = apps.get_model("images", "ImageOfTheDay")
    entries = ImageOfTheDay.objects.select_related("image__collection__source")

    unresolved = []
    for entry in entries:
        image = entry.image
        region_id = (
            image.region_id
            or image.collection.region_id
            or image.collection.source.region_id
        )
        if region_id is None:
            unresolved.append(entry)
            continue
        entry.region_id = region_id
        entry.save(update_fields=["region"])

    if unresolved:
        days = ", ".join(f"{entry.day:%Y-%m-%d}" for entry in unresolved)
        raise RuntimeError(
            f"{len(unresolved)} Image of the Day entries ({days}) belong to no "
            "region after the legacy-region backfill."
        )


# Frozen full-table copy of CollectionRegionStats.REFRESH_SQL. The table is
# empty when this runs, so the stale-row arm is unnecessary. ON CONFLICT keeps
# the statement safely re-runnable.
BACKFILL_COLLECTION_REGION_STATS_SQL = """
WITH region_expansion AS (
    SELECT r.id AS region_id, r.id AS counts_toward_id
    FROM regions_region r
    UNION
    SELECT ra.region_id, r2.id
    FROM regions_regionancestor ra
    JOIN regions_region r2 ON r2.wikidata_item_id = ra.ancestor_id
),
image_rows AS MATERIALIZED (
    SELECT
        img.id,
        c.id AS collection_id,
        img.will_not_georef,
        COALESCE(img.region_id, c.region_id, s.region_id) AS region_id,
        conf.confidence
    FROM images_collection c
    JOIN images_source s ON s.id = c.source_id
    JOIN images_image img
        ON img.collection_id = c.id AND img.duplicate_of_id IS NULL
    LEFT JOIN LATERAL (
        SELECT CASE WHEN img.aerial THEN (
            SELECT ag.confidence FROM images_aerialgeoreference ag
            WHERE ag.image_id = img.id
            ORDER BY ag.georeferenced_at DESC LIMIT 1
        ) ELSE (
            SELECT g.confidence FROM images_georeference g
            WHERE g.image_id = img.id
            ORDER BY g.georeferenced_at DESC LIMIT 1
        ) END AS confidence
    ) conf ON TRUE
)
INSERT INTO images_collectionregionstats (
    collection_id, region_id, total_images, will_not_georef_images,
    georeferenced_low, georeferenced_medium, georeferenced_high, updated_at
)
SELECT
    ir.collection_id,
    exp.counts_toward_id,
    COUNT(ir.id),
    COUNT(ir.id) FILTER (WHERE ir.will_not_georef),
    COUNT(ir.id) FILTER (WHERE NOT ir.will_not_georef AND ir.confidence = 'low'),
    COUNT(ir.id) FILTER (WHERE NOT ir.will_not_georef AND ir.confidence = 'medium'),
    COUNT(ir.id) FILTER (WHERE NOT ir.will_not_georef AND ir.confidence = 'high'),
    NOW()
FROM image_rows ir
JOIN region_expansion exp ON exp.region_id = ir.region_id
GROUP BY ir.collection_id, exp.counts_toward_id
ON CONFLICT (collection_id, region_id) DO UPDATE SET
    total_images = EXCLUDED.total_images,
    will_not_georef_images = EXCLUDED.will_not_georef_images,
    georeferenced_low = EXCLUDED.georeferenced_low,
    georeferenced_medium = EXCLUDED.georeferenced_medium,
    georeferenced_high = EXCLUDED.georeferenced_high,
    updated_at = EXCLUDED.updated_at
"""


def backfill_collection_region_stats(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(BACKFILL_COLLECTION_REGION_STATS_SQL)


class Migration(migrations.Migration):
    # The legacy backfills write rows referenced by foreign keys that later
    # operations tighten or index. PostgreSQL must commit those writes before
    # it can alter the tables without pending deferred-trigger events.
    atomic = False

    dependencies = [
        ("images", "0063_duplicateimagepair_uuid"),
        ("regions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="collection",
            name="region",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Region this collection's images depict, unless overridden "
                    "on an image"
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="collections",
                to="regions.region",
            ),
        ),
        migrations.AddField(
            model_name="image",
            name="region",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Region this image depicts; falls back to the collection's, "
                    "then the source's"
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="images",
                to="regions.region",
            ),
        ),
        migrations.AddField(
            model_name="source",
            name="region",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Region this source's images depict, unless overridden on a "
                    "collection or image"
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sources",
                to="regions.region",
            ),
        ),
        migrations.RunPython(
            provision_legacy_region,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AddField(
            model_name="imageoftheday",
            name="region",
            field=models.ForeignKey(
                help_text=IMAGE_OF_THE_DAY_REGION_HELP_TEXT,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="featured_days",
                to="regions.region",
            ),
        ),
        migrations.RunPython(
            backfill_image_of_the_day_regions,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AlterField(
            model_name="imageoftheday",
            name="region",
            field=models.ForeignKey(
                help_text=IMAGE_OF_THE_DAY_REGION_HELP_TEXT,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="featured_days",
                to="regions.region",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="imageoftheday",
            name="unique_image_of_the_day",
        ),
        migrations.AddConstraint(
            model_name="imageoftheday",
            constraint=models.UniqueConstraint(
                deferrable=models.Deferrable.DEFERRED,
                fields=("region", "day"),
                name="unique_image_of_the_day_per_region",
            ),
        ),
        migrations.RemoveIndex(
            model_name="imageoftheday",
            name="images_imag_locked_5fed40_idx",
        ),
        migrations.AddIndex(
            model_name="imageoftheday",
            index=models.Index(
                fields=["region", "locked"],
                name="images_imag_region__6c00b4_idx",
            ),
        ),
        migrations.AlterModelOptions(
            name="imageoftheday",
            options={
                "ordering": ["region", "day"],
                "verbose_name": "Image of the Day",
                "verbose_name_plural": "Images of the Day",
            },
        ),
        migrations.CreateModel(
            name="CollectionRegionStats",
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
                ("total_images", models.PositiveIntegerField(default=0)),
                (
                    "will_not_georef_images",
                    models.PositiveIntegerField(default=0),
                ),
                ("georeferenced_low", models.PositiveIntegerField(default=0)),
                ("georeferenced_medium", models.PositiveIntegerField(default=0)),
                ("georeferenced_high", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "collection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="region_stats",
                        to="images.collection",
                    ),
                ),
                (
                    "region",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="collection_stats",
                        to="regions.region",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "collection region stats",
                "indexes": [
                    models.Index(
                        fields=["region"], name="images_coll_region__9c0823_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("collection", "region"),
                        name="collectionregionstats_unique_pair",
                    )
                ],
            },
        ),
        migrations.RunPython(
            backfill_collection_region_stats,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="home_subjects_image",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Photograph labelled in the homepage's subjects band. Pick "
                    "one whose tagged subjects read as a caption of what is in "
                    "the frame. The band is hidden while this is empty, while "
                    "the photograph has no subjects, and while it sits in a "
                    "private collection or source."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="images.image",
            ),
        ),
    ]
