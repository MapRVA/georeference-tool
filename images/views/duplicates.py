from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Max
from django.shortcuts import render

from ..models import DuplicateImagePair


@staff_member_required
def duplicate_image_pairs(request):
    """
    Staff review page for nightly-computed candidate visual-duplicate pairs.

    Pairs whose image_a or image_b has since been marked duplicate_of are
    hidden, so the list reflects only unresolved candidates even between the
    nightly scans that rebuild the table.
    """
    pairs = list(
        DuplicateImagePair.objects.select_related(
            "image_a",
            "image_b",
            "image_a__collection",
            "image_a__collection__source",
            "image_b__collection",
            "image_b__collection__source",
        )
        .filter(
            image_a__duplicate_of__isnull=True,
            image_b__duplicate_of__isnull=True,
        )
        .order_by("distance")
    )
    total = DuplicateImagePair.objects.count()
    last_run = DuplicateImagePair.objects.aggregate(Max("computed_at"))[
        "computed_at__max"
    ]
    context = {
        "pairs": pairs,
        "last_run": last_run,
        "resolved_count": total - len(pairs),
    }
    return render(request, "images/duplicate_image_pairs.html", context)
