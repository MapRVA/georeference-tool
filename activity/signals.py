from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from images.models import AerialGeoreference, Georeference, Image

from .models import (
    GROUPING_WINDOW,
    MILESTONE_THRESHOLDS,
    SITEWIDE_MILESTONE_THRESHOLDS,
    GeoreferenceGroup,
    GeoreferenceGroupMember,
    SitewideMilestone,
    UserMilestone,
)


@receiver(post_save, sender=Georeference)
def handle_georeference_created(sender, instance, created, **kwargs):
    """Create or update GeoreferenceGroup when a point georeference is created."""
    if not created:
        return

    # Always check sitewide milestones, even for anonymous submissions
    transaction.on_commit(lambda: _check_sitewide_milestone(instance.georeferenced_at))

    if not instance.georeferenced_by:
        return

    transaction.on_commit(
        lambda: _process_georeference(
            user=instance.georeferenced_by,
            timestamp=instance.georeferenced_at,
            georeference=instance,
            aerial_georeference=None,
        )
    )


@receiver(post_save, sender=AerialGeoreference)
def handle_aerial_georeference_created(sender, instance, created, **kwargs):
    """Create or update GeoreferenceGroup when an aerial georeference is created."""
    if not created:
        return

    # Always check sitewide milestones, even for anonymous submissions
    transaction.on_commit(lambda: _check_sitewide_milestone(instance.georeferenced_at))

    if not instance.georeferenced_by:
        return

    transaction.on_commit(
        lambda: _process_georeference(
            user=instance.georeferenced_by,
            timestamp=instance.georeferenced_at,
            georeference=None,
            aerial_georeference=instance,
        )
    )


def _process_georeference(user, timestamp, georeference, aerial_georeference):
    """
    Process a new georeference: add to existing group or create new one,
    and check for milestones.
    """
    # Find user's most recent group
    latest_group = (
        GeoreferenceGroup.objects.filter(user=user).order_by("-ended_at").first()
    )

    # If within 3 hours of last activity, add to existing group
    if latest_group and (timestamp - latest_group.ended_at) < GROUPING_WINDOW:
        latest_group.ended_at = timestamp
        latest_group.count += 1
        latest_group.save(update_fields=["ended_at", "count"])
        group = latest_group
    else:
        # Start new group
        group = GeoreferenceGroup.objects.create(
            user=user,
            started_at=timestamp,
            ended_at=timestamp,
            count=1,
        )

    # Create the member link
    GeoreferenceGroupMember.objects.create(
        group=group,
        georeference=georeference,
        aerial_georeference=aerial_georeference,
        added_at=timestamp,
    )

    # Check for user milestones (sitewide milestones checked in signal handler)
    _check_milestone(user, timestamp)


def _check_milestone(user, timestamp):
    """Check if the user has crossed a milestone threshold and record it."""
    total = (
        Georeference.objects.filter(georeferenced_by=user).count()
        + AerialGeoreference.objects.filter(georeferenced_by=user).count()
    )

    for milestone in MILESTONE_THRESHOLDS:
        if total >= milestone:
            UserMilestone.objects.get_or_create(
                user=user,
                count=milestone,
                defaults={"reached_at": timestamp},
            )


def _check_sitewide_milestone(timestamp):
    """Check if the site has crossed a sitewide milestone threshold and record it."""
    # Count distinct georeferenced images (not georeference submissions)
    point_count = Image.objects.filter(
        aerial=False,
        duplicate_of__isnull=True,
        will_not_georef=False,
        georeferences__isnull=False,
    ).count()

    aerial_count = Image.objects.filter(
        aerial=True,
        duplicate_of__isnull=True,
        will_not_georef=False,
        aerial_georeferences__isnull=False,
    ).count()

    total = point_count + aerial_count

    for milestone in SITEWIDE_MILESTONE_THRESHOLDS:
        if total >= milestone:
            SitewideMilestone.objects.get_or_create(
                count=milestone,
                defaults={"reached_at": timestamp},
            )
