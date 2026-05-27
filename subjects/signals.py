"""Auto-maintain ``Subject.representative_image`` from ``SubjectMapping`` events.

The browse page renders ``Subject.representative_image`` directly via
``select_related``, so every Subject with mapped images must have a non-null
value. These handlers keep that invariant without touching the explicit
admin/user override.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from images.models import SubjectMapping, TopRatedImageView


@receiver(post_save, sender=SubjectMapping)
def _set_representative_on_new_mapping(sender, instance, created, **kwargs):
    """Seed ``representative_image`` with the first mapped image.

    Only fires on creation, and only when the Subject has no representative
    yet — a user-chosen representative is never overwritten.
    """
    if not created:
        return

    from .models import Subject

    Subject.objects.filter(
        pk=instance.subject_id,
        representative_image__isnull=True,
    ).update(representative_image_id=instance.image_id)


@receiver(post_delete, sender=SubjectMapping)
def _reelect_representative_on_mapping_delete(sender, instance, **kwargs):
    """Re-elect a representative if the deleted mapping was the chosen one.

    Triggered both by explicit mapping removal and by Image deletion (which
    cascades to ``SubjectMapping``). The FK is ``SET_NULL`` on Image delete,
    so by the time this runs the Subject's ``representative_image_id`` may
    already be null — either way, pick another mapped image.
    """
    from .models import Subject

    try:
        subject = Subject.objects.get(pk=instance.subject_id)
    except Subject.DoesNotExist:
        return

    if (
        subject.representative_image_id is not None
        and subject.representative_image_id != instance.image_id
    ):
        return

    remaining_image_ids = (
        SubjectMapping.objects.filter(subject_id=instance.subject_id)
        .order_by("image_id")
        .values_list("image_id", flat=True)
    )

    top_rated = (
        TopRatedImageView.objects.filter(image_id__in=remaining_image_ids)
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    if top_rated is not None:
        new_rep_id = top_rated.image_id
    else:
        new_rep_id = remaining_image_ids.first()

    if subject.representative_image_id != new_rep_id:
        Subject.objects.filter(
            pk=instance.subject_id,
            representative_image_id=subject.representative_image_id,
        ).update(representative_image_id=new_rep_id)
