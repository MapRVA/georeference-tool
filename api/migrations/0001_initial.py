import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from oauth2_provider.settings import oauth2_settings


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        migrations.swappable_dependency(oauth2_settings.APPLICATION_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ApplicationConsent",
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
                    "scope",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Space-separated scopes the user has granted.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="consents",
                        to=oauth2_settings.APPLICATION_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="oauth_consents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="applicationconsent",
            constraint=models.UniqueConstraint(
                fields=("user", "application"),
                name="unique_consent_per_user_application",
            ),
        ),
    ]
