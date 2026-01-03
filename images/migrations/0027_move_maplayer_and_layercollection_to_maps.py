from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('images', '0026_update_public_georeferences_mvt_thumbnail'),
    ]

    operations = [
        # Rename the tables from images_* to maps_*
        # and remove the models from Django's state for the images app
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterModelTable(
                    name='layercollection',
                    table='maps_layercollection',
                ),
            ],
            state_operations=[
                migrations.DeleteModel(
                    name='LayerCollection',
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterModelTable(
                    name='maplayer',
                    table='maps_maplayer',
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='maplayer',
                    name='collection',
                ),
                migrations.DeleteModel(
                    name='MapLayer',
                ),
            ],
        ),
    ]
