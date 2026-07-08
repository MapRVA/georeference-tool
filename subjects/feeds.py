from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Rss201rev2Feed

from images.models import Image
from subjects.models import Subject

class SubjectActivityFeed(Feed):
    """
    Subject-specific RSS feed showing new photos tagged with a given subject.
    """
    feed_type = Rss201rev2Feed

    def get_object(self, request, subject_slug):
        # Grabs the subject object when the URL is requested
        return get_object_or_404(Subject, slug=subject_slug)

    def title(self, subject):
        return f"Yesterdays - New images for {subject.name}"

    def link(self, obj):
        if hasattr(obj, 'get_absolute_url'):
            return obj.get_absolute_url()
        return f"/subjects/{obj.pk}/"

    def description(self, subject):
        return f"Latest images tagged with: {subject.name}."

    def items(self, obj):
        # Assuming SubjectMapping links Image and Subject via a ForeignKey to Subject.
        # The related lookup name (`subjectmapping__subject`) might need to be tweaked
        # depending on your exact ForeignKey setup in SubjectMapping.
        return Image.objects.filter(
            subjectmapping__subject=obj
        ).distinct().order_by('-created_at')[:50]

    def item_title(self, item):
        return f"New image tagged: {item.title}"

    def item_description(self, item):
        return item.description

    def item_link(self, item):
        if hasattr(item, 'get_absolute_url'):
            return item.get_absolute_url()
        return f"/images/{item.pk}/"

    def item_pubdate(self, item):
        return getattr(item, 'created_at', None)
