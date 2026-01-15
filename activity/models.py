from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models

GROUPING_WINDOW = timedelta(hours=3)
MILESTONE_THRESHOLDS = getattr(
    settings,
    "ACTIVITY_MILESTONE_THRESHOLDS",
    [5, 15, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
)


class GeoreferenceGroup(models.Model):
    """Groups georeferences by a user within a 3-hour window."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="georeference_groups"
    )
    started_at = models.DateTimeField(
        help_text="Timestamp of the first georeference in this group"
    )
    ended_at = models.DateTimeField(
        db_index=True,
        help_text="Timestamp of the most recent georeference in this group",
    )
    count = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.user.first_name or self.user.username} georeferenced {self.count} images"

    class Meta:
        ordering = ["-ended_at"]
        indexes = [
            models.Index(fields=["-ended_at"]),
            models.Index(fields=["user", "-ended_at"]),
        ]


class GeoreferenceGroupMember(models.Model):
    """Links individual georeferences to their group."""

    group = models.ForeignKey(
        GeoreferenceGroup, on_delete=models.CASCADE, related_name="members"
    )
    georeference = models.OneToOneField(
        "images.Georeference", on_delete=models.CASCADE, null=True, blank=True
    )
    aerial_georeference = models.OneToOneField(
        "images.AerialGeoreference", on_delete=models.CASCADE, null=True, blank=True
    )
    added_at = models.DateTimeField(
        help_text="Timestamp when this georeference was made"
    )

    def __str__(self):
        if self.georeference:
            return f"Member: {self.georeference.image}"
        elif self.aerial_georeference:
            return f"Member: {self.aerial_georeference.image}"
        return f"Member #{self.pk}"

    @property
    def image(self):
        """Return the image from whichever georeference type is set."""
        if self.georeference:
            return self.georeference.image
        elif self.aerial_georeference:
            return self.aerial_georeference.image
        return None

    class Meta:
        ordering = ["-added_at"]


class UserMilestone(models.Model):
    """Records when a user reaches a georeference milestone."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="milestones")
    count = models.PositiveIntegerField(
        help_text="The milestone count reached (5, 15, 50, etc.)"
    )
    reached_at = models.DateTimeField(
        db_index=True, help_text="Timestamp when this milestone was reached"
    )

    def __str__(self):
        return f"{self.user.first_name or self.user.username} reached {self.count} georeferences"

    class Meta:
        ordering = ["-reached_at"]
        unique_together = [["user", "count"]]
        indexes = [
            models.Index(fields=["-reached_at"]),
        ]
