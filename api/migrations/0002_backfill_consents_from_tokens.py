from django.db import migrations


def backfill_consents(apps, schema_editor):
    """Seed consent records from tokens issued before this model existed.

    Users who authorized an application before remembered consent shipped
    should keep skipping the consent screen, and their apps should appear
    (and be revocable) on the authorized-applications page, which now lists
    consents rather than access tokens.
    """
    AccessToken = apps.get_model("oauth2_provider", "AccessToken")
    ApplicationConsent = apps.get_model("api", "ApplicationConsent")

    scopes_by_grant = {}
    tokens = AccessToken.objects.exclude(user__isnull=True).exclude(
        application__isnull=True
    )
    for user_id, application_id, scope in tokens.values_list(
        "user_id", "application_id", "scope"
    ):
        scopes_by_grant.setdefault((user_id, application_id), set()).update(
            (scope or "").split()
        )

    ApplicationConsent.objects.bulk_create(
        [
            ApplicationConsent(
                user_id=user_id,
                application_id=application_id,
                scope=" ".join(sorted(scopes)),
            )
            for (user_id, application_id), scopes in scopes_by_grant.items()
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0001_initial"),
        ("oauth2_provider", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_consents, migrations.RunPython.noop),
    ]
