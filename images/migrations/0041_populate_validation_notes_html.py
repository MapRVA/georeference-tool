from django.db import migrations


def populate_validation_notes_html(apps, schema_editor):
    """Populate cached HTML fields for existing validation notes."""
    from images.utils import render_markdown_safe

    GeoreferenceValidation = apps.get_model("images", "GeoreferenceValidation")
    AerialGeoreferenceValidation = apps.get_model(
        "images", "AerialGeoreferenceValidation"
    )

    for validation in GeoreferenceValidation.objects.filter(notes_html=""):
        if validation.notes:
            validation.notes_html = render_markdown_safe(validation.notes)
            validation.save(update_fields=["notes_html"])

    for validation in AerialGeoreferenceValidation.objects.filter(notes_html=""):
        if validation.notes:
            validation.notes_html = render_markdown_safe(validation.notes)
            validation.save(update_fields=["notes_html"])


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0040_aerialgeoreferencevalidation_notes_html_and_more"),
    ]

    operations = [
        migrations.RunPython(
            populate_validation_notes_html, migrations.RunPython.noop
        ),
    ]
