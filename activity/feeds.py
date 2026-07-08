from itertools import chain
from operator import attrgetter

from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Rss201rev2Feed


from activity.models import (
    GeoreferenceGroup,
    SitewideMilestone,
    SubjectIntroduction,
    UserMilestone,
)

MAX_ITEMS = 50


class SitewideActivityFeed(Feed):
    """
    Site-wide RSS feed showing the latest image additions.
    """
    feed_type = Rss201rev2Feed
    title = "Yesterdays - Site-wide Activity"
    link = "/activity/"  # Update with your main activity page URL
    description = "The latest historical images, georeferences, and tags from Yesterdays."

    def items(self):
        # Fetch the most recent items of each activity type.
        # Adjust 'created_at' to match your actual datetime field (e.g., 'timestamp').
        georefs = GeoreferenceGroup.objects.all().order_by('-created_at')[:MAX_ITEMS]
        subjects = SubjectIntroduction.objects.all().order_by('-created_at')[:MAX_ITEMS]
        user_milestones = UserMilestone.objects.all().order_by('-created_at')[:MAX_ITEMS]
        sitewide_milestones = SitewideMilestone.objects.all().order_by('-created_at')[:MAX_ITEMS]

        # Chain them together and sort chronologically
        combined = sorted(
            chain(georefs, subjects, user_milestones, sitewide_milestones),
            key=attrgetter('created_at'),
            reverse=True
        )
        return combined[:MAX_ITEMS]

    def item_title(self, item):
        if isinstance(item, GeoreferenceGroup):
            return f"Images georeferenced by {getattr(item, 'user', 'a user')}"
        elif isinstance(item, SubjectIntroduction):
            return f"New subject added: {item.subject.title}"
        elif isinstance(item, UserMilestone):
            return f"{item.user.username} reached {item.count} georeferences!"
        elif isinstance(item, SitewideMilestone):
            return f"Yesterdays reached {item.count} images georeferenced!"
        return str(item)

    def item_description(self, item):
        if isinstance(item, GeoreferenceGroup):
            count = getattr(item, 'count', 'Multiple')
            return f"{count} images were recently georeferenced."
        elif isinstance(item, SubjectIntroduction):
            return "A new subject was introduced to the catalog."
        elif isinstance(item, UserMilestone):
            return "A user has reached a new georeferencing milestone."
        elif isinstance(item, SitewideMilestone):
            return "The community has reached a new site-wide milestone."
        return str(item)

    def item_link(self, item):
        if hasattr(item, 'get_absolute_url'):
            return item.get_absolute_url()
        if isinstance(item, SubjectIntroduction) and hasattr(item, 'subject'):
            return f"/subjects/{item.subject.pk}/"
        return "/activity/"

    def item_pubdate(self, item):
        return getattr(item, 'created_at', None)
