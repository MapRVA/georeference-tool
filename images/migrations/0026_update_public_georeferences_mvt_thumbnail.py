from django.db import migrations

# SQL to create the updated materialized view with thumbnail
CREATE_MATERIALIZED_VIEW = """
CREATE MATERIALIZED VIEW public_georeferences_mvt AS
WITH latest_georeferences AS (
    SELECT
        g.*,
        ROW_NUMBER() OVER (PARTITION BY g.image_id ORDER BY g.georeferenced_at DESC) as rn
    FROM images_georeference g
)
SELECT
    g.id as georeference_id,
    i.id as image_id,
    g.point,
    ST_Transform(g.point, 3857) as point_3857,
    COALESCE(i.thumbnail, i.permalink) as thumbnail,
    i.original_date,
    i.edtf_date,
    i.start_decdate,
    i.fuzzy_start_decdate,
    i.end_decdate,
    i.fuzzy_end_decdate,
    COALESCE(i.scale, 0) as scale,
    g.direction,
    g.confidence
FROM latest_georeferences g
JOIN images_image i ON g.image_id = i.id
JOIN images_collection c ON i.collection_id = c.id
JOIN images_source s ON c.source_id = s.id
WHERE g.rn = 1
AND c.public = true
AND s.public = true
AND i.will_not_georef = false
AND i.duplicate_of_id IS NULL;
"""

# Create spatial index for fast bounding box queries
CREATE_SPATIAL_INDEX = """
CREATE INDEX idx_public_georeferences_mvt_point_3857
ON public_georeferences_mvt
USING GIST(point_3857);
"""

# Create UNIQUE index required for CONCURRENT refreshes
# This allows REFRESH MATERIALIZED VIEW CONCURRENTLY to work without locking
CREATE_UNIQUE_INDEX = """
CREATE UNIQUE INDEX idx_public_georeferences_mvt_georeference_id
ON public_georeferences_mvt (georeference_id);
"""

# SQL to drop the materialized view
DROP_MATERIALIZED_VIEW = (
    "DROP MATERIALIZED VIEW IF EXISTS public_georeferences_mvt CASCADE;"
)


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0025_image_thumbnail"),
    ]

    operations = [
        # Drop the old materialized view
        migrations.RunSQL(
            DROP_MATERIALIZED_VIEW,
            # Reverse SQL would recreate the old view - we'll define it below
            migrations.RunSQL.noop,
        ),
        # Create the new materialized view with thumbnail field
        migrations.RunSQL(
            CREATE_MATERIALIZED_VIEW + CREATE_SPATIAL_INDEX + CREATE_UNIQUE_INDEX,
            DROP_MATERIALIZED_VIEW,
        ),
    ]
