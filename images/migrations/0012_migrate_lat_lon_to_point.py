from django.db import migrations
import django.contrib.gis.db.models.fields
from django.contrib.gis.geos import Point


def migrate_data(apps, schema_editor):
    Georeference = apps.get_model('images', 'Georeference')
    for row in Georeference.objects.all():
        # The model state at this point still has latitude and longitude
        if row.latitude is not None and row.longitude is not None:
            row.point = Point(x=row.longitude, y=row.latitude, srid=4326)
            row.save(update_fields=['point'])


class Migration(migrations.Migration):

    dependencies = [
        ('images', '0011_alter_wikidataitem_image_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='georeference',
            name='point',
            field=django.contrib.gis.db.models.fields.PointField(null=True, srid=4326),
        ),
        migrations.RunPython(migrate_data, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='georeference',
            name='latitude',
        ),
        migrations.RemoveField(
            model_name='georeference',
            name='longitude',
        ),
        migrations.AlterField(
            model_name='georeference',
            name='point',
            field=django.contrib.gis.db.models.fields.PointField(srid=4326),
        ),
    ]
