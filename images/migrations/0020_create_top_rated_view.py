from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0019_imagerating"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Database operations: create the actual view
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    CREATE VIEW images_top_rated_view AS
                    SELECT
                        img.id AS image_id,
                        COALESCE(AVG(ir.rating), 0) AS avg_rating,
                        COUNT(ir.id) AS vote_count,
                        -- For sorting: rated images first, then by rating, then by votes
                        -- When rating is null, use -1 to sort unrated images last
                        CASE
                            WHEN COUNT(ir.id) > 0 THEN COALESCE(AVG(ir.rating), 0)
                            ELSE -1
                        END AS sort_value
                    FROM
                        images_image img
                    LEFT JOIN
                        images_imagerating ir ON img.id = ir.image_id
                    LEFT JOIN
                        images_collection col ON img.collection_id = col.id
                    LEFT JOIN
                        images_source src ON col.source_id = src.id
                    WHERE
                        col.public = TRUE AND
                        src.public = TRUE AND
                        img.duplicate_of_id IS NULL
                    GROUP BY
                        img.id;
                    """,
                    reverse_sql="DROP VIEW images_top_rated_view;",
                ),
            ],
            # State operations: create the model in Django's state
            state_operations=[
                migrations.CreateModel(
                    name="TopRatedImageView",
                    fields=[
                        (
                            "image_id",
                            models.IntegerField(primary_key=True, serialize=False),
                        ),
                        ("avg_rating", models.FloatField()),
                        ("vote_count", models.IntegerField()),
                        ("sort_value", models.FloatField()),
                    ],
                    options={
                        "db_table": "images_top_rated_view",
                        "managed": False,
                    },
                ),
            ],
        ),
    ]
