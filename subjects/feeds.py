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

    def get_object(self, request, subject_id):
        # Grabs the subject object when the URL is requested
        return get_object_or_404(Subject, pk=subject_id)

    def title(self, obj):
        name = getattr(obj, 'name', f"Subject {obj.id}")
        return f"Yesterdays - New images for {name}"

    def link(self, obj):
        if hasattr(obj, 'get_absolute_url'):
            return obj.get_absolute_url()
        return f"/subjects/{obj.pk}/"

    def description(self, obj):
        name = getattr(obj, 'name', f"Subject {obj.id}")
        return f"Latest images tagged with: {name}."

    def items(self, obj):
        # Assuming SubjectMapping links Image and Subject via a ForeignKey to Subject.
        # The related lookup name (`subjectmapping__subject`) might need to be tweaked
        # depending on your exact ForeignKey setup in SubjectMapping.
        return Image.objects.filter(
            subjectmapping__subject=obj
        ).distinct().order_by('-created_at')[:50]

    def item_title(self, item):
        title = getattr(item, 'title', f"Image {item.id}")
        return f"New image tagged: {title}"

    def item_description(self, item):
        return getattr(item, 'description', 'A historical image was tagged with this subject.')

    def item_link(self, item):
        if hasattr(item, 'get_absolute_url'):
            return item.get_absolute_url()
        return f"/images/{item.pk}/"

    def item_pubdate(self, item):
        return getattr(item, 'created_at', None)
