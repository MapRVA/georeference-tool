from django.contrib.gis.geos import Point
from django.core.paginator import Page, Paginator
from django.db.models import Avg, Case, Count, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, render

from ..models import (
    Collection,
    Image,
    ImageRating,
    Source,
    Subject,
    TopRatedImageView,
)
from ..utils import render_markdown_safe


def apply_image_filters(request, queryset):
    """
    Apply standard filters from filter_cards.html to a queryset.

    This is a unified helper function used across all views that include
    the filter_cards.html partial.

    Supports:
    - georeference_status: georeferenced, pending, will_not_georef
    - start_year, end_year: year range filtering
    - with_subjects: images that have ALL specified subjects
    - without_subjects: images that don't have ANY specified subjects
    - no_subjects: images with no subjects at all
    """
    # Get filter parameters from URL
    georeference_status = (
        request.GET.get("georeference_status", "").split(",")
        if request.GET.get("georeference_status")
        else []
    )
    start_year = request.GET.get("start_year")
    end_year = request.GET.get("end_year")
    with_subjects = (
        request.GET.get("with_subjects", "").split(",")
        if request.GET.get("with_subjects")
        else []
    )
    without_subjects = (
        request.GET.get("without_subjects", "").split(",")
        if request.GET.get("without_subjects")
        else []
    )
    no_subjects = request.GET.get("no_subjects") == "true"

    # Apply year filtering
    if start_year:
        try:
            start_year_int = int(start_year)
            queryset = queryset.filter(
                Q(fuzzy_start_decdate__gte=start_year_int)
                | Q(start_decdate__gte=start_year_int)
            )
        except ValueError:
            pass

    if end_year:
        try:
            end_year_int = int(end_year)
            queryset = queryset.filter(
                Q(fuzzy_end_decdate__lte=end_year_int)
                | Q(end_decdate__lte=end_year_int)
            )
        except ValueError:
            pass

    # Apply subject filtering
    if no_subjects:
        queryset = queryset.filter(subjects__isnull=True)
    elif with_subjects:
        # Include only images with ALL of these subjects
        for subject_id in with_subjects:
            if subject_id:
                queryset = queryset.filter(subjects__id=subject_id)
    elif without_subjects:
        # Exclude images with ANY of these subjects
        queryset = queryset.exclude(subjects__id__in=without_subjects)

    # Apply georeference status filtering
    if georeference_status:
        # Build the filter conditions based on selected statuses
        filter_conditions = Q()

        if "georeferenced" in georeference_status:
            filter_conditions |= Q(georeferences__isnull=False) | Q(
                aerial=True, aerial_georeferences__isnull=False
            )

        if "pending" in georeference_status:
            filter_conditions |= (
                Q(georeferences__isnull=True)
                & Q(aerial=False)
                & Q(will_not_georef=False)
            ) | (
                Q(aerial_georeferences__isnull=True)
                & Q(aerial=True)
                & Q(will_not_georef=False)
            )

        if "will_not_georef" in georeference_status:
            filter_conditions |= Q(will_not_georef=True)

        # Apply the filter if any conditions were added
        if filter_conditions:
            queryset = queryset.filter(filter_conditions)

    return queryset


def browse_sources(request):
    """Browse all public sources"""
    sources = (
        Source.objects.filter(public=True)
        .prefetch_related("collections")
        .order_by("name")
    )

    # Add statistics for each source (only from public collections)
    total_collections = 0
    total_images = 0
    total_georeferenced = 0

    for source in sources:
        # Count only public collections for this source
        source.public_collections_count = source.collections.filter(public=True).count()
        total_collections += source.public_collections_count

        source.total_images = Image.objects.filter(
            collection__source=source,
            collection__public=True,
            duplicate_of__isnull=True,
        ).count()
        source.georeferenced_images = (
            Image.objects.filter(
                collection__source=source,
                collection__public=True,
                duplicate_of__isnull=True,
                georeferences__isnull=False,
            )
            .distinct()
            .count()
        )
        source.pending_images = source.total_images - source.georeferenced_images

        # Add to overall totals
        total_images += source.total_images
        total_georeferenced += source.georeferenced_images

    # Calculate overall statistics
    overall_stats = {
        "total_sources": sources.count(),
        "total_collections": total_collections,
        "total_images": total_images,
        "total_georeferenced": total_georeferenced,
        "georeferenced_percentage": round((total_georeferenced / total_images * 100), 1)
        if total_images > 0
        else 0,
    }

    # Get top-rated image from entire site for Open Graph metadata
    top_rated_entry = (
        TopRatedImageView.objects.all()
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    top_rated_image = None
    if top_rated_entry:
        top_rated_image = Image.objects.select_related("collection__source").get(
            id=top_rated_entry.image_id
        )

    context = {
        "sources": sources,
        "overall_stats": overall_stats,
        "top_rated_image": top_rated_image,
    }
    return render(request, "images/browse_sources.html", context)


def source_detail(request, slug):
    """Detail view for a specific source showing its public collections"""
    source = get_object_or_404(Source, slug=slug, public=True)
    collections = source.collections.filter(public=True)

    # Add statistics for each collection
    for collection in collections:
        collection.total_images = collection.images.filter(
            duplicate_of__isnull=True
        ).count()
        collection.georeferenced_images = (
            collection.images.filter(
                duplicate_of__isnull=True, georeferences__isnull=False
            )
            .distinct()
            .count()
        )
        will_not_georef_images = collection.images.filter(
            duplicate_of__isnull=True, will_not_georef=True
        ).count()
        collection.pending_images = (
            collection.total_images
            - collection.georeferenced_images
            - will_not_georef_images
        )

    # Overall source statistics (only from public collections, excluding duplicates)
    total_images = Image.objects.filter(
        collection__source=source, collection__public=True, duplicate_of__isnull=True
    ).count()
    georeferenced_images = (
        Image.objects.filter(
            collection__source=source,
            collection__public=True,
            duplicate_of__isnull=True,
            georeferences__isnull=False,
        )
        .distinct()
        .count()
    )

    # Get top-rated image for Open Graph metadata
    top_rated_entry = (
        TopRatedImageView.objects.filter(
            image_id__in=Image.objects.filter(
                collection__source=source, collection__public=True
            ).values_list("id", flat=True)
        )
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    top_rated_image = None
    if top_rated_entry:
        top_rated_image = Image.objects.select_related("collection__source").get(
            id=top_rated_entry.image_id
        )

    context = {
        "source": source,
        "collections": collections,
        "total_images": total_images,
        "georeferenced_images": georeferenced_images,
        "pending_images": total_images
        - georeferenced_images
        - Image.objects.filter(
            collection__source=source,
            collection__public=True,
            duplicate_of__isnull=True,
            will_not_georef=True,
        ).count(),
        "completion_percentage": (georeferenced_images / total_images * 100)
        if total_images > 0
        else 0,
        "top_rated_image": top_rated_image,
    }
    return render(request, "images/source_detail.html", context)


def collection_detail(request, source_slug, collection_slug):
    """Detail view for a specific public collection"""
    source = get_object_or_404(Source, slug=source_slug, public=True)
    collection = get_object_or_404(
        Collection, source=source, slug=collection_slug, public=True
    )

    # Get filter parameters from URL
    georeference_status = (
        request.GET.get("georeference_status", "").split(",")
        if request.GET.get("georeference_status")
        else []
    )
    start_year = request.GET.get("start_year")
    end_year = request.GET.get("end_year")
    with_subjects = (
        request.GET.get("with_subjects", "").split(",")
        if request.GET.get("with_subjects")
        else []
    )
    without_subjects = (
        request.GET.get("without_subjects", "").split(",")
        if request.GET.get("without_subjects")
        else []
    )
    no_subjects = request.GET.get("no_subjects") == "true"

    # Sort images: georeferenced images second-to-last, "will not reference" images at the end
    # Exclude duplicate images from the collection view
    images = (
        collection.images.filter(duplicate_of__isnull=True)
        .prefetch_related("subjects")
        .annotate(
            has_georeference=Case(
                When(
                    Q(georeferences__isnull=False)
                    | Q(aerial=True, aerial_georeferences__isnull=False),
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("will_not_georef", "has_georeference", "id")
    )

    # Apply year filtering
    if start_year:
        try:
            start_year_int = int(start_year)
            images = images.filter(
                Q(fuzzy_start_decdate__gte=start_year_int)
                | Q(start_decdate__gte=start_year_int)
            )
        except ValueError:
            pass

    if end_year:
        try:
            end_year_int = int(end_year)
            images = images.filter(
                Q(fuzzy_end_decdate__lte=end_year_int)
                | Q(end_decdate__lte=end_year_int)
            )
        except ValueError:
            pass

    # Apply subject filtering
    if no_subjects:
        images = images.filter(subjects__isnull=True)
    elif with_subjects:
        # Include only images with ALL of these subjects
        for subject_id in with_subjects:
            if subject_id:
                images = images.filter(subjects__id=subject_id)
    elif without_subjects:
        # Exclude images with ANY of these subjects
        images = images.exclude(subjects__id__in=without_subjects)

    # Apply georeference status filtering
    if georeference_status:
        # Build the filter conditions based on selected statuses
        filter_conditions = Q()

        if "georeferenced" in georeference_status:
            filter_conditions |= Q(georeferences__isnull=False) | Q(
                aerial=True, aerial_georeferences__isnull=False
            )

        if "pending" in georeference_status:
            filter_conditions |= (
                Q(georeferences__isnull=True)
                & Q(aerial=False)
                & Q(will_not_georef=False)
            )

        if "will_not_georef" in georeference_status:
            filter_conditions |= Q(will_not_georef=True)

        # Apply the filter if any conditions were added
        if filter_conditions:
            images = images.filter(filter_conditions)
    # Get counts before filtering for statistics
    all_images = collection.images.filter(duplicate_of__isnull=True)
    total_images = all_images.distinct().count()

    # Count images as georeferenced if they have point georeferences OR aerials with polygon georeferences
    georeferenced_images = (
        all_images.filter(
            Q(georeferences__isnull=False)
            | Q(aerial=True, aerial_georeferences__isnull=False)
        )
        .distinct()
        .count()
    )
    will_not_georef_images = all_images.filter(will_not_georef=True).count()

    # Paginate the filtered images for browsing
    paginator = Paginator(images.distinct(), 24)  # 24 images per page for grid layout
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Get top-rated image for Open Graph metadata
    top_rated_entry = (
        TopRatedImageView.objects.filter(
            image_id__in=Image.objects.filter(collection=collection).values_list(
                "id", flat=True
            )
        )
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    top_rated_image = None
    if top_rated_entry:
        top_rated_image = Image.objects.select_related("collection__source").get(
            id=top_rated_entry.image_id
        )

    context = {
        "source": source,
        "collection": collection,
        "page_obj": page_obj,
        "total_images": total_images,
        "georeferenced_images": georeferenced_images,
        "pending_images": total_images - georeferenced_images - will_not_georef_images,
        "completion_percentage": (georeferenced_images / total_images * 100)
        if total_images > 0
        else 0,
        "top_rated_image": top_rated_image,
    }
    return render(request, "images/collection_detail.html", context)


def image_list(request):
    """List all images with filtering options"""
    images = (
        Image.objects.filter(collection__public=True, collection__source__public=True)
        .select_related("collection__source")
        .prefetch_related("georeferences")
    )

    # Filter by georeferencing status
    status = request.GET.get("status")
    if status == "pending":
        images = images.filter(georeferences__isnull=True, will_not_georef=False)
    elif status == "georeferenced":
        images = images.filter(georeferences__isnull=False).distinct()
    elif status == "will_not_georef":
        images = images.filter(will_not_georef=True)

    # Filter by difficulty
    difficulty = request.GET.get("difficulty")
    if difficulty in ["easy", "medium", "hard"]:
        images = images.filter(difficulty=difficulty)

    # Filter by collection
    collection_id = request.GET.get("collection")
    if collection_id:
        images = images.filter(collection_id=collection_id)

    # Pagination
    paginator = Paginator(images, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "status": status,
        "difficulty": difficulty,
        "collection_id": collection_id,
    }

    return render(request, "images/image_list.html", context)


def image_detail(request, image_id):
    """Display detailed view of an image for georeferencing"""
    image = get_object_or_404(Image, id=image_id)

    # Render confidence notes as markdown for the current georeference
    georeference = image.get_georeference()
    rendered_notes = None
    if georeference and georeference.confidence_notes:
        rendered_notes = render_markdown_safe(georeference.confidence_notes)

    # Render notes for all georeferences in the timeline
    georeferences_with_notes = []
    for geo in image.georeferences.all():
        rendered_geo_notes = None
        if geo.confidence_notes:
            rendered_geo_notes = render_markdown_safe(geo.confidence_notes)
        georeferences_with_notes.append(
            {
                "georeference": geo,
                "rendered_notes": rendered_geo_notes,
            }
        )

    # Build timeline combining georeferences and comments in chronological order
    timeline_items = []

    # Add georeferences
    for geo in image.georeferences.all():
        rendered_geo_notes = None
        if geo.confidence_notes:
            rendered_geo_notes = render_markdown_safe(geo.confidence_notes)
        timeline_items.append(
            {
                "type": "georeference",
                "timestamp": geo.georeferenced_at,
                "georeference": geo,
                "rendered_notes": rendered_geo_notes,
            }
        )

    # Add aerial georeferences
    for aerial_geo in image.aerial_georeferences.all():
        rendered_aerial_notes = None
        if aerial_geo.confidence_notes:
            rendered_aerial_notes = render_markdown_safe(aerial_geo.confidence_notes)
        timeline_items.append(
            {
                "type": "aerial_georeference",
                "timestamp": aerial_geo.georeferenced_at,
                "aerial_georeference": aerial_geo,
                "rendered_notes": rendered_aerial_notes,
            }
        )

    # Add comments
    for comment in image.comments.all():
        rendered_comment_text = None
        if comment.text:
            rendered_comment_text = render_markdown_safe(comment.text)
        timeline_items.append(
            {
                "type": "comment",
                "timestamp": comment.created_at,
                "comment": comment,
                "rendered_text": rendered_comment_text,
            }
        )

    # Sort by timestamp (oldest first, newest at bottom)
    timeline_items.sort(key=lambda x: x["timestamp"], reverse=False)

    # Get total count of images in this collection
    total_images_in_collection = image.collection.images.count()

    # Get the position of this image in the collection (ordered by ID)
    image_position = image.collection.images.filter(id__lte=image.id).count()

    # Get rating statistics
    image_ratings = image.ratings.all()
    avg_rating = image_ratings.aggregate(Avg("rating"))["rating__avg"]
    rating_count = image_ratings.count()
    user_rating = None
    if request.user.is_authenticated:
        try:
            user_rating = ImageRating.objects.get(image=image, user=request.user).rating
        except ImageRating.DoesNotExist:
            pass

    context = {
        "image": image,
        "has_georeference": image.georeferences.exists(),
        "georeference": georeference,
        "rendered_notes": rendered_notes,
        "validations": georeference.validations.all() if georeference else [],
        "georeferences_with_notes": georeferences_with_notes,
        "polygonal_georeference": image.get_aerial_georeference()
        if image.aerial
        else None,
        "timeline_items": timeline_items,
        "next_image": image.get_next_image(),
        "previous_image": image.get_previous_image(),
        "total_images_in_collection": total_images_in_collection,
        "image_position": image_position,
        "avg_rating": avg_rating,
        "rating_count": rating_count,
        "user_rating": user_rating,
    }

    return render(request, "images/image_detail.html", context)


def top_rated_images(request):
    """Display paginated list of highest-rated images, optionally filtered by source or collection"""
    page_number = request.GET.get("page", 1)
    page_size = 24  # 24 images per page

    # Get optional filters
    source_id = request.GET.get("source")
    collection_id = request.GET.get("collection")

    # Convert page number to offset/limit
    try:
        page_number = int(page_number)
        if page_number < 1:
            page_number = 1
    except (ValueError, TypeError):
        page_number = 1

    # Start with all view entries
    view_entries = TopRatedImageView.objects.all()

    # Filter by source if specified
    if source_id:
        view_entries = view_entries.filter(
            image_id__in=Image.objects.filter(
                collection__source_id=source_id
            ).values_list("id", flat=True)
        )

    # Filter by collection if specified
    if collection_id:
        view_entries = view_entries.filter(
            image_id__in=Image.objects.filter(collection_id=collection_id).values_list(
                "id", flat=True
            )
        )

    # Order by rating
    view_entries = view_entries.order_by(
        "-sort_value", "-avg_rating", "-vote_count", "image_id"
    )

    # Get total count for pagination info
    total_count = view_entries.count()

    # Calculate total pages
    total_pages = (total_count + page_size - 1) // page_size

    # Validate page number
    if page_number > total_pages and total_count > 0:
        page_number = total_pages

    offset = (page_number - 1) * page_size

    # Get image IDs for current page only
    page_image_ids = list(
        view_entries[offset : offset + page_size].values_list("image_id", flat=True)
    )

    # Create a queryset for the current page only, maintaining the correct order
    if page_image_ids:
        preserved_order = Case(
            *[
                When(pk=image_id, then=pos)
                for pos, image_id in enumerate(page_image_ids)
            ]
        )
        page_images = list(
            Image.objects.filter(id__in=page_image_ids)
            .select_related("collection__source")
            .order_by(preserved_order)
        )
    else:
        page_images = []

    # Create a Django Paginator that uses our manually-paginated queryset
    # but has the correct count for all pages
    paginator = Paginator(page_images, page_size)

    # Override the count to match the total from the database view
    paginator.count = total_count

    # We already have our page data, so just need to set up the Page object
    page_obj = Page(page_images, page_number, paginator)

    # Calculate statistics from the view
    stats = TopRatedImageView.objects.aggregate(
        total_rated=Count("image_id", filter=Q(vote_count__gt=0)),
        total_unrated=Count("image_id", filter=Q(vote_count=0)),
    )

    # Get top-rated image for Open Graph metadata (first from the ordered list)
    top_rated_image = page_images[0] if page_images else None

    context = {
        "page_obj": page_obj,
        "total_rated": stats["total_rated"],
        "total_unrated": stats["total_unrated"],
        "total_images": stats["total_rated"] + stats["total_unrated"],
        "top_rated_image": top_rated_image,
    }
    return render(request, "images/favorites.html", context)


def browse_aerials(request):
    """Browse all aerial images with optional location-based filtering"""

    # Start with base queryset
    aerials = (
        Image.objects.filter(
            aerial=True,
            collection__public=True,
            collection__source__public=True,
            duplicate_of__isnull=True,
        )
        .select_related("collection__source")
        .prefetch_related("subjects")
    )

    # Apply standard filters from filter_cards.html
    aerials = apply_image_filters(request, aerials)

    # Check for location filtering
    lat = request.GET.get("lat")
    lon = request.GET.get("lon")
    is_filtered = False
    filter_point = None

    if lat and lon:
        try:
            lat = float(lat)
            lon = float(lon)

            # Validate coordinates are within reasonable bounds
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                # Create a Point from the coordinates
                filter_point = Point(lon, lat)

                # Filter images that have aerial georeferences containing this point
                filtered_image_ids = []
                for aerial in aerials:
                    aerial_georeference = aerial.get_aerial_georeference()
                    if aerial_georeference and aerial_georeference.polygon.contains(
                        filter_point
                    ):
                        filtered_image_ids.append(aerial.id)

                # Debug output
                print(f"Filter point: {filter_point}")
                print(f"Total aerials before filter: {aerials.count()}")
                print(f"Filtered image IDs: {filtered_image_ids}")

                # Apply the filter - even if empty list (this will show no results)
                aerials = aerials.filter(id__in=filtered_image_ids)
                is_filtered = True

                print(f"Total aerials after filter: {aerials.count()}")

        except (ValueError, TypeError):
            # Invalid coordinates, ignore filtering
            pass

    # Sort filtered results by georeference area (smallest to largest) if filtered
    if is_filtered and filter_point:
        # Get aerial georeferences and sort by area
        aerial_with_areas = []
        for aerial in aerials:
            aerial_georeference = aerial.get_aerial_georeference()
            if aerial_georeference:
                # Calculate area using PostGIS
                area = aerial_georeference.polygon.area
                aerial_with_areas.append((area, aerial.id))

        # Sort by area and get ordered IDs
        aerial_with_areas.sort(key=lambda x: x[0])
        ordered_ids = [item[1] for item in aerial_with_areas]

        # Preserve the order in the queryset
        if ordered_ids:
            preserved_order = Case(
                *[When(pk=pk, then=pos) for pos, pk in enumerate(ordered_ids)]
            )
            aerials = aerials.order_by(preserved_order)
    else:
        # Default ordering for non-filtered results
        aerials = aerials.order_by("id")

    # Paginate images for browsing
    paginator = Paginator(aerials, 24)  # 24 images per page for grid layout
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Calculate statistics
    total_images = aerials.count()
    georeferenced_images = (
        aerials.filter(aerial_georeferences__isnull=False).distinct().count()
    )
    will_not_georef_images = aerials.filter(will_not_georef=True).count()

    # Get top-rated aerial image for Open Graph metadata
    top_rated_entry = (
        TopRatedImageView.objects.filter(
            image_id__in=Image.objects.filter(aerial=True).values_list("id", flat=True)
        )
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    top_rated_image = None
    if top_rated_entry:
        top_rated_image = Image.objects.select_related("collection__source").get(
            id=top_rated_entry.image_id
        )

    context = {
        "page_obj": page_obj,
        "total_images": total_images,
        "georeferenced_images": georeferenced_images,
        "pending_images": total_images - georeferenced_images - will_not_georef_images,
        "completion_percentage": (georeferenced_images / total_images * 100)
        if total_images > 0
        else 0,
        "is_filtered": is_filtered,
        "filter_lat": lat if is_filtered else None,
        "filter_lon": lon if is_filtered else None,
        "top_rated_image": top_rated_image,
    }
    return render(request, "images/from_above.html", context)


def browse_subjects(request):
    """Browse all subjects"""
    subjects = (
        Subject.objects.all()
        .select_related("wikidata_item")
        .prefetch_related("image_mappings__image")
    )

    # Add statistics for each subject
    for subject in subjects:
        # Count images associated with this subject (excluding duplicates)
        subject.total_images = subject.image_mappings.filter(
            image__duplicate_of__isnull=True,
            image__collection__public=True,
            image__collection__source__public=True,
        ).count()
        subject.georeferenced_images = (
            subject.image_mappings.filter(
                image__duplicate_of__isnull=True,
                image__collection__public=True,
                image__collection__source__public=True,
                image__georeferences__isnull=False,
            )
            .distinct()
            .count()
        )

        subject.pending_images = subject.total_images - subject.georeferenced_images

    # Filter out subjects with no images and sort by total_images in descending order, then by title
    subjects = [s for s in subjects if s.total_images > 0]
    subjects = sorted(subjects, key=lambda s: (-s.total_images, s.title))

    # Calculate overall statistics
    total_subjects = len(subjects)
    total_images = sum(subject.total_images for subject in subjects)
    total_georeferenced = sum(subject.georeferenced_images for subject in subjects)

    overall_stats = {
        "total_subjects": total_subjects,
        "total_images": total_images,
        "total_georeferenced": total_georeferenced,
        "georeferenced_percentage": round((total_georeferenced / total_images * 100), 1)
        if total_images > 0
        else 0,
    }

    # Paginate subjects for browsing
    paginator = Paginator(subjects, 12)  # 12 subjects per page for grid layout
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Get top-rated image from entire site for Open Graph metadata
    top_rated_entry = (
        TopRatedImageView.objects.all()
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    top_rated_image = None
    if top_rated_entry:
        top_rated_image = Image.objects.select_related("collection__source").get(
            id=top_rated_entry.image_id
        )

    context = {
        "page_obj": page_obj,
        "overall_stats": overall_stats,
        "top_rated_image": top_rated_image,
    }
    return render(request, "images/browse_subjects.html", context)


def subject_detail(request, subject_slug):
    """Detail view for a specific subject showing its images"""
    subject = get_object_or_404(Subject, slug=subject_slug)

    # Get filter parameters from URL
    georeference_status = (
        request.GET.get("georeference_status", "").split(",")
        if request.GET.get("georeference_status")
        else []
    )
    start_year = request.GET.get("start_year")
    end_year = request.GET.get("end_year")
    with_subjects = (
        request.GET.get("with_subjects", "").split(",")
        if request.GET.get("with_subjects")
        else []
    )
    without_subjects = (
        request.GET.get("without_subjects", "").split(",")
        if request.GET.get("without_subjects")
        else []
    )
    no_subjects = request.GET.get("no_subjects") == "true"

    # Get images associated with this subject (only from public collections, excluding duplicates)
    images = (
        Image.objects.filter(
            subject_mappings__subject=subject,
            collection__public=True,
            collection__source__public=True,
            duplicate_of__isnull=True,
        )
        .select_related("collection__source")
        .prefetch_related("subjects")
        .annotate(
            has_georeference=Case(
                When(
                    Q(georeferences__isnull=False)
                    | Q(aerial=True, aerial_georeferences__isnull=False),
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("will_not_georef", "has_georeference", "id")
    )

    # Apply year filtering
    if start_year:
        try:
            start_year_int = int(start_year)
            images = images.filter(
                Q(fuzzy_start_decdate__gte=start_year_int)
                | Q(start_decdate__gte=start_year_int)
            )
        except ValueError:
            pass

    if end_year:
        try:
            end_year_int = int(end_year)
            images = images.filter(
                Q(fuzzy_end_decdate__lte=end_year_int)
                | Q(end_decdate__lte=end_year_int)
            )
        except ValueError:
            pass

    # Apply additional subject filtering (beyond the main subject)
    if no_subjects:
        # This doesn't make sense for a subject detail view, but keep for consistency
        images = images.filter(subjects__isnull=True)
    elif with_subjects:
        # Include only images with ALL of these subjects (in addition to the main subject)
        for subject_id in with_subjects:
            if subject_id and subject_id != str(subject.id):
                images = images.filter(subjects__id=subject_id)
    elif without_subjects:
        # Exclude images with ANY of these subjects
        exclude_ids = [sid for sid in without_subjects if sid != str(subject.id)]
        if exclude_ids:
            images = images.exclude(subjects__id__in=exclude_ids)

    # Apply georeference status filtering
    if georeference_status:
        # Build the filter conditions based on selected statuses
        filter_conditions = Q()

        if "georeferenced" in georeference_status:
            filter_conditions |= Q(georeferences__isnull=False) | Q(
                aerial=True, aerial_georeferences__isnull=False
            )

        if "pending" in georeference_status:
            filter_conditions |= (
                Q(georeferences__isnull=True)
                & Q(aerial=False)
                & Q(will_not_georef=False)
            )

        if "will_not_georef" in georeference_status:
            filter_conditions |= Q(will_not_georef=True)

        # Apply the filter if any conditions were added
        if filter_conditions:
            images = images.filter(filter_conditions)

    # Get counts before filtering for statistics
    all_images = Image.objects.filter(
        subject_mappings__subject=subject,
        duplicate_of__isnull=True,
        collection__public=True,
        collection__source__public=True,
    )
    total_images = all_images.count()
    georeferenced_images = (
        all_images.filter(georeferences__isnull=False).distinct().count()
    )
    pending_images = (
        total_images
        - georeferenced_images
        - all_images.filter(will_not_georef=True).count()
    )

    # Paginate the filtered images for browsing
    paginator = Paginator(images.distinct(), 24)  # 24 images per page for grid layout
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Check if subject has images with embeddings for similarity search
    has_images_with_embeddings = all_images.filter(embedding__isnull=False).exists()

    # Get top-rated image from this subject for Open Graph metadata
    top_rated_entry = (
        TopRatedImageView.objects.filter(
            image_id__in=all_images.values_list("id", flat=True)
        )
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    top_rated_image = None
    if top_rated_entry:
        top_rated_image = Image.objects.select_related("collection__source").get(
            id=top_rated_entry.image_id
        )

    context = {
        "subject": subject,
        "page_obj": page_obj,
        "total_images": total_images,
        "georeferenced_images": georeferenced_images,
        "pending_images": pending_images,
        "completion_percentage": (georeferenced_images / total_images * 100)
        if total_images > 0
        else 0,
        "has_images_with_embeddings": has_images_with_embeddings,
        "top_rated_image": top_rated_image,
    }
    return render(request, "images/subject_detail.html", context)
