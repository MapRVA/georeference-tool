from django.db import migrations

BACKFILL_SQL = """
WITH ranked AS (
    SELECT sm.subject_id,
           sm.image_id,
           ROW_NUMBER() OVER (
               PARTITION BY sm.subject_id
               ORDER BY COALESCE(trv.sort_value, -1) DESC,
                        COALESCE(trv.avg_rating, -1) DESC,
                        COALESCE(trv.vote_count, 0) DESC,
                        sm.image_id ASC
           ) AS rn
      FROM images_subjectmapping sm
      LEFT JOIN images_top_rated_view trv ON trv.image_id = sm.image_id
      JOIN subjects_subject s ON s.id = sm.subject_id
     WHERE s.representative_image_id IS NULL
)
UPDATE subjects_subject s
   SET representative_image_id = ranked.image_id
  FROM ranked
 WHERE ranked.rn = 1
   AND ranked.subject_id = s.id
   AND s.representative_image_id IS NULL;
"""


def backfill_representative_images(apps, schema_editor):
    """Seed Subject.representative_image for every Subject with mapped images.

    Priority mirrors the old ``Subject.get_representative_image()`` helper:
    top-rated mapped image first (by TopRatedImageView's sort_value,
    avg_rating, vote_count), then lowest image_id as a tiebreaker / fallback
    when no mapping has a TopRatedImageView row.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(BACKFILL_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("subjects", "0015_delete_address"),
        ("images", "0052_backfill_subject_mapping_activity_groups"),
    ]

    # Reverse is a noop: nulling values out would just re-trigger the slow
    # view-time path this migration exists to eliminate, and the forward op
    # is idempotent so re-running is safe.
    operations = [
        migrations.RunPython(
            backfill_representative_images,
            migrations.RunPython.noop,
        ),
    ]
