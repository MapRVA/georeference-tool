from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0056_imageoftheday_note_html"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="home_feed_show_new_collections",
            field=models.BooleanField(
                default=True,
                help_text="Show new collection announcements in the homepage feed embed",
            ),
        ),
    ]
