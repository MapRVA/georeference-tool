import json
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.gis.geos import Point
from django.core.paginator import Paginator
from django.db import IntegrityError, models, transaction
from django.db.models import Case, Func, IntegerField, Value, When
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

# Try to import PostgreSQL search functions
try:
    from django.contrib.postgres.search import (
        SearchQuery,
        SearchRank,
        SearchVector,
        TrigramSimilarity,
    )

    HAS_POSTGRES_SEARCH = True
except ImportError:
    HAS_POSTGRES_SEARCH = False

# Import CLIP dependencies (only when needed for search)
try:
    import clip
    import torch

    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False

from .models import (
    Album,
    Collection,
    Comment,
    Georeference,
    GeoreferenceValidation,
    Image,
    ImageSkip,
    LayerCollection,
    Source,
    Subject,
    SubjectMapping,
    WikidataItem,
)
from .utils import render_markdown_safe

# Defines the minimum zoom level at which a scale becomes visible.
# At a given zoom level, all images with a scale value greater than or equal to
# the determined scale for that zoom level will be displayed.
SCALE_VISIBILITY = {
    0: 5,  # Scale 5 and up visible from this zoom
    10: 4,  # Scale 4 and up visible from this zoom
    11: 3,  # Scale 3 and up visible from this zoom
    12: 2,  # Scale 2 and up visible from this zoom
    14: 1,  # Scale 1 and up visible from this zoom
}


def get_min_scale_for_zoom(z):
    """
    Determines the minimum image scale to display for a given map zoom level.
    Returns None if no scales should be visible at this zoom level.
    """
    min_scale_to_show = None
    for zoom_threshold, scale in sorted(SCALE_VISIBILITY.items()):
        if z >= zoom_threshold:
            min_scale_to_show = scale
        else:
            break  # Since zoom levels are sorted, no need to check further
    return min_scale_to_show


@xframe_options_exempt
def map_embed(request):
    """
    A view to display a map that can be embedded in other websites.
    Accepts query parameters to configure the map.
    """
    context = {
        "image_id": request.GET.get("image_id"),
        "collection_id": request.GET.get("collection_id"),
        "source_id": request.GET.get("source_id"),
        "subject_id": request.GET.get("subject_id"),
        "center_lng": request.GET.get("center_lng"),
        "center_lat": request.GET.get("center_lat"),
        "zoom_level": request.GET.get("zoom_level"),
        "include_geocoder": request.GET.get("include_geocoder", "false").lower()
        == "true",
        "enable_scale_visibility": request.GET.get(
            "enable_scale_visibility", "false"
        ).lower()
        == "true",
        "zoom_to_contents": request.GET.get("zoom_to_contents", "true").lower()
        == "true",
        "geolocate": request.GET.get("geolocate", "false").lower() == "true",
        "hash": request.GET.get("hash", "false").lower() == "true",
        "map_id": request.GET.get("map_id", "embedded-map"),
    }
    return render(request, "images/map_embed.html", context)


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

    context = {
        "sources": sources,
        "overall_stats": overall_stats,
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
    }
    return render(request, "images/source_detail.html", context)


def collection_detail(request, source_slug, collection_slug):
    """Detail view for a specific public collection"""
    source = get_object_or_404(Source, slug=source_slug, public=True)
    collection = get_object_or_404(
        Collection, source=source, slug=collection_slug, public=True
    )

    # Sort images: georeferenced images second-to-last, "will not reference" images at the end
    # Exclude duplicate images from the collection view
    images = (
        collection.images.filter(duplicate_of__isnull=True)
        .annotate(
            has_georeference=Case(
                When(georeferences__isnull=False, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("will_not_georef", "has_georeference", "id")
    )
    total_images = images.distinct().count()
    georeferenced_images = images.filter(georeferences__isnull=False).distinct().count()
    will_not_georef_images = collection.images.filter(
        duplicate_of__isnull=True, will_not_georef=True
    ).count()

    # Paginate images for browsing
    paginator = Paginator(images, 24)  # 24 images per page for grid layout
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

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
    }
    return render(request, "images/collection_detail.html", context)


def georeference_interface(request):
    """Main georeferencing interface - can be filtered by source/collection/subject/album or show specific image"""
    source_slug = request.GET.get("source")
    collection_slug = request.GET.get("collection")
    subject_slug = request.GET.get("subject")
    difficulty = request.GET.get("difficulty")
    image_id = request.GET.get("image")
    album_id = request.GET.get("album")

    # If specific image ID is requested, try to load it
    current_image = None
    if image_id:
        try:
            # For specific image requests, allow both georeferenced and ungeoreferenced images
            # This enables corrections for already georeferenced images
            # But exclude duplicate images
            current_image = Image.objects.get(
                id=int(image_id),
                will_not_georef=False,
                duplicate_of__isnull=True,
                collection__public=True,
                collection__source__public=True,
            )
        except (Image.DoesNotExist, ValueError):
            # If specific image not found or invalid, fall back to random selection
            pass

    # Start with all ungeoreferenced images from public sources/collections
    # Exclude duplicate images from being suggested
    images = Image.objects.filter(
        georeferences__isnull=True,
        will_not_georef=False,
        duplicate_of__isnull=True,
        collection__public=True,
        collection__source__public=True,
    )

    # Note: We deliberately do NOT exclude skipped images here because:
    # 1. It makes the remaining count misleading (looks like fewer images need work)
    # 2. Users should be able to go back and georeference images they previously skipped
    # 3. Skip tracking is still useful for statistics, but shouldn't hide images

    images = images.select_related("collection__source")

    # Filter by album if specified
    album = None
    album_owner_display_name = None
    if album_id:
        try:
            album = Album.objects.get(id=album_id)
            # Check if album is public or if user is the owner
            if not album.public and (not request.user.is_authenticated or album.owner != request.user):
                # Private album and user is not the owner - return 404
                raise Http404("Album not found")
            # Filter images to only those in this album
            images = images.filter(albums=album)
            # Get the album owner's display name for the breadcrumb
            album_owner_display_name = (
                album.owner.get_display_name()
                if hasattr(album.owner, "get_display_name")
                else album.owner.username
            )
        except Album.DoesNotExist:
            raise Http404("Album not found")

    # Filter by source if specified
    source = None
    if source_slug:
        source = get_object_or_404(Source, slug=source_slug, public=True)
        images = images.filter(collection__source=source, collection__public=True)

    # Filter by collection if specified
    collection = None
    if collection_slug and source:
        collection = get_object_or_404(
            Collection, source=source, slug=collection_slug, public=True
        )
        images = images.filter(collection=collection)

    # Filter by subject if specified
    subject = None
    if subject_slug:
        subject = get_object_or_404(Subject, slug=subject_slug)
        images = images.filter(subject_mappings__subject=subject)

    # Filter by difficulty if specified - can be multiple values (plus-separated)
    difficulty_param = request.GET.get("difficulty", "")
    difficulty_filters = []
    if difficulty_param:
        # Split plus-separated values and validate
        difficulty_filters = [
            d.strip()
            for d in difficulty_param.split("+")
            if d.strip() in ["easy", "medium", "hard", "unlabeled"]
        ]
        if difficulty_filters:
            # Handle unlabeled separately since it needs a different query
            regular_difficulties = [d for d in difficulty_filters if d != "unlabeled"]
            has_unlabeled = "unlabeled" in difficulty_filters

            if regular_difficulties and has_unlabeled:
                # Include both regular difficulties and unlabeled images
                images = images.filter(
                    models.Q(difficulty__in=regular_difficulties)
                    | models.Q(difficulty__isnull=True)
                )
            elif regular_difficulties:
                # Only regular difficulties
                images = images.filter(difficulty__in=regular_difficulties)
            elif has_unlabeled:
                # Only unlabeled images
                images = images.filter(difficulty__isnull=True)

    # If no specific image or it wasn't found, select randomly from filtered set
    if not current_image:
        # Get a random image for georeferencing
        current_image = images.order_by("?").first()

    # Set source and collection from the current image if not already set
    if current_image:
        if not source_slug:
            source = current_image.collection.source
        if not collection_slug:
            collection = current_image.collection

    context = {
        "current_image": current_image,
        "source": source,
        "collection": collection,
        "subject": subject,
        "album": album,
        "album_owner_display_name": album_owner_display_name,
        "difficulty_filters": difficulty_filters,
        "difficulty_filters_json": json.dumps(difficulty_filters),
        "remaining_count": images.count(),
    }

    # Remove duplicate message - template already shows appropriate message when no image available

    return render(request, "images/georeference_interface.html", context)


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

    context = {
        "image": image,
        "has_georeference": image.georeferences.exists(),
        "georeference": georeference,
        "rendered_notes": rendered_notes,
        "validations": georeference.validations.all() if georeference else [],
        "georeferences_with_notes": georeferences_with_notes,
        "timeline_items": timeline_items,
        "next_image": image.get_next_image(),
        "previous_image": image.get_previous_image(),
        "total_images_in_collection": total_images_in_collection,
        "image_position": image_position,
    }

    return render(request, "images/image_detail.html", context)


@require_http_methods(["POST"])
@csrf_exempt
def georeference_image(request, image_id):
    """API endpoint to georeference an image"""
    try:
        data = json.loads(request.body)
        image = get_object_or_404(Image, id=image_id)

        # Check if image is a duplicate
        if image.duplicate_of:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Cannot georeference duplicate images. This image is marked as a duplicate of another image.",
                },
                status=400,
            )

        # For anonymous users, check if they can still georeference
        # For authenticated users, allow corrections (multiple submissions)
        if not request.user.is_authenticated:
            # Anonymous users can only georeference if no georeferences exist yet
            if image.georeferences.exists():
                return JsonResponse(
                    {
                        "success": False,
                        "error": "This image has already been georeferenced. Please login to submit a correction.",
                    },
                    status=400,
                )
        # Note: Authenticated users can always submit (the unique constraint in the model
        # prevents duplicate submissions by the same user, but we'll handle that gracefully)

        # Validate required fields
        required_fields = ["latitude", "longitude", "confidence"]
        for field in required_fields:
            if field not in data:
                return JsonResponse(
                    {"success": False, "error": f"Missing required field: {field}"},
                    status=400,
                )

        # Validate confidence level
        valid_confidence_levels = ["low", "medium", "high"]
        if data["confidence"] not in valid_confidence_levels:
            return JsonResponse(
                {"success": False, "error": "Invalid confidence level"},
                status=400,
            )

        # Validate rule: low confidence requires notes
        if data["confidence"] == "low" and not data.get("notes", "").strip():
            return JsonResponse(
                {
                    "success": False,
                    "error": "Low confidence requires explanatory notes",
                },
                status=400,
            )

        # Handle georeference creation/update with proper transaction handling
        georeference = None

        # First, try to create a new georeference
        try:
            with transaction.atomic():
                georeference = Georeference.objects.create(
                    image=image,
                    point=Point(float(data["longitude"]), float(data["latitude"])),
                    direction=int(data["direction"]) if data.get("direction") else None,
                    confidence=data["confidence"],
                    georeferenced_by=request.user
                    if request.user.is_authenticated
                    else None,
                    confidence_notes=data.get("notes", ""),
                )
        except IntegrityError:
            # User has already georeferenced this image, update their existing georeference
            if request.user.is_authenticated:
                with transaction.atomic():
                    georeference = Georeference.objects.filter(
                        image=image, georeferenced_by=request.user
                    ).first()
                    if georeference:
                        georeference.point = Point(
                            float(data["longitude"]), float(data["latitude"])
                        )
                        georeference.direction = (
                            int(data["direction"]) if data.get("direction") else None
                        )
                        georeference.confidence = data["confidence"]
                        georeference.confidence_notes = data.get("notes", "")
                        georeference.save()
                    else:
                        # This shouldn't happen, but handle it gracefully
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Unable to update existing georeference",
                            },
                            status=500,
                        )
            else:
                # This shouldn't happen for anonymous users given our check above
                return JsonResponse(
                    {"success": False, "error": "Unable to create georeference"},
                    status=500,
                )

        return JsonResponse(
            {
                "success": True,
                "georeference_id": georeference.id,
                "message": "Image successfully georeferenced",
            }
        )

    except (ValueError, TypeError) as e:
        return JsonResponse(
            {"success": False, "error": f"Invalid data format: {str(e)}"}, status=400
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def validate_georeference(request, georeference_id):
    """API endpoint to validate a georeference"""
    # Check if user is authenticated
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )
    try:
        data = json.loads(request.body)
        georeference = get_object_or_404(Georeference, id=georeference_id)

        # Check if user is trying to validate their own work
        if georeference.georeferenced_by == request.user:
            return JsonResponse(
                {"success": False, "error": "Cannot validate your own georeference"},
                status=400,
            )

        # Check if user has already validated this georeference
        if GeoreferenceValidation.objects.filter(
            georeference=georeference, validated_by=request.user
        ).exists():
            return JsonResponse(
                {
                    "success": False,
                    "error": "You have already validated this georeference",
                },
                status=400,
            )

        validation_choice = data.get("validation")
        if validation_choice not in ["correct", "incorrect", "uncertain"]:
            return JsonResponse(
                {"success": False, "error": "Invalid validation choice"}, status=400
            )

        with transaction.atomic():
            validation = GeoreferenceValidation.objects.create(
                georeference=georeference,
                validated_by=request.user,
                validation=validation_choice,
                notes=data.get("notes", ""),
            )

        return JsonResponse(
            {
                "success": True,
                "validation_id": validation.id,
                "message": "Validation recorded successfully",
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def add_comment(request, image_id):
    """API endpoint to add a comment to an image"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )

    try:
        data = json.loads(request.body)
        image = get_object_or_404(Image, id=image_id)

        comment_text = data.get("text", "").strip()
        if not comment_text:
            return JsonResponse(
                {"success": False, "error": "Comment text is required"}, status=400
            )

        comment = Comment.objects.create(
            image=image, text=comment_text, commented_by=request.user
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Comment added successfully",
                "comment_id": comment.id,
            },
            status=201,
        )
    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON in request body"}, status=400
        )
    except Image.DoesNotExist:
        return JsonResponse({"success": False, "error": "Image not found"}, status=404)
    except Exception as e:
        import traceback

        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def skip_image(request, image_id):
    """API endpoint to skip an image"""
    try:
        data = json.loads(request.body)
        image = get_object_or_404(Image, id=image_id)

        # Only track skips for authenticated users
        if request.user.is_authenticated:
            with transaction.atomic():
                # Always allow skipping - don't check if already skipped
                # This lets users skip multiple times if they want
                skip, created = ImageSkip.objects.get_or_create(
                    image=image,
                    user=request.user,
                    defaults={"reason": data.get("reason", "")},
                )

        # For anonymous users, we just return success without tracking
        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_http_methods(["POST"])
def mark_difficulty(request, image_id):
    """Mark the difficulty of an image (admin only)"""
    # Check if user is authenticated and is staff
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )

    if not request.user.is_staff:
        return JsonResponse(
            {"success": False, "error": "Admin permissions required"}, status=403
        )

    image = get_object_or_404(Image, id=image_id)
    difficulty = request.POST.get("difficulty")

    if difficulty in ["easy", "medium", "hard"]:
        image.difficulty = difficulty
        image.save(update_fields=["difficulty"])
        return JsonResponse(
            {"success": True, "message": f"Image marked as {difficulty}"}
        )
    else:
        return JsonResponse(
            {"success": False, "error": "Invalid difficulty level"}, status=400
        )


@require_http_methods(["POST"])
def mark_scale(request, image_id):
    """Mark the scale of an image (admin only)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse(
            {"success": False, "error": "Admin permissions required"}, status=403
        )

    image = get_object_or_404(Image, id=image_id)
    scale = request.POST.get("scale")

    if scale == "none":
        image.scale = None
        image.save(update_fields=["scale"])
        return JsonResponse({"success": True, "message": "Image scale removed"})

    try:
        scale_val = int(scale)
        if 1 <= scale_val <= 5:
            image.scale = scale_val
            image.save(update_fields=["scale"])
            return JsonResponse(
                {"success": True, "message": f"Image scale marked as {scale}"}
            )
        else:
            return JsonResponse(
                {"success": False, "error": "Invalid scale value"}, status=400
            )
    except (ValueError, TypeError):
        return JsonResponse(
            {"success": False, "error": "Invalid scale value"}, status=400
        )


def edit_album(request, album_id):
    """Edit album title and description (owner only)"""
    if not request.user.is_authenticated:
        return redirect("login")

    album = get_object_or_404(Album, id=album_id)

    # Check that the user is the owner
    if album.owner != request.user:
        raise Http404("Album not found")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()

        # Validate title
        if not title:
            messages.error(request, "Album title is required.")
            return render(
                request,
                "images/album_edit.html",
                {
                    "album": album,
                    "profile_user": album.owner,
                    "display_name": album.owner.get_display_name()
                    if hasattr(album.owner, "get_display_name")
                    else album.owner.username,
                },
            )

        if len(title) > 500:
            messages.error(request, "Album title must be 500 characters or less.")
            return render(
                request,
                "images/album_edit.html",
                {
                    "album": album,
                    "profile_user": album.owner,
                    "display_name": album.owner.get_display_name()
                    if hasattr(album.owner, "get_display_name")
                    else album.owner.username,
                },
            )

        # Update album
        album.title = title
        album.description = description
        album.save(update_fields=["title", "description"])

        messages.success(request, "Album updated successfully.")
        return redirect(
            "images:album_detail",
            display_name=album.owner.get_display_name() if hasattr(album.owner, 'get_display_name') else album.owner.username,
            album_id=album.id,
        )

    # GET request - display the edit form
    display_name = (
        album.owner.get_display_name()
        if hasattr(album.owner, "get_display_name")
        else album.owner.username
    )

    context = {
        "album": album,
        "profile_user": album.owner,
        "display_name": display_name,
    }

    return render(request, "images/album_edit.html", context)


def delete_album(request, album_id):
    """Delete album (owner only) - confirmation page"""
    if not request.user.is_authenticated:
        return redirect("login")

    album = get_object_or_404(Album, id=album_id)

    # Check that the user is the owner
    if album.owner != request.user:
        raise Http404("Album not found")

    if request.method == "POST":
        # Confirm deletion
        album_title = album.title
        # Get the display name (OSM username) for the redirect
        # Special case: hardcoded_admin needs to use the Django username
        if album.owner.username == "hardcoded_admin":
            album_owner_username = "hardcoded_admin"
        else:
            album_owner_username = (
                album.owner.get_display_name()
                if hasattr(album.owner, "get_display_name")
                else album.owner.username
            )
        album.delete()
        messages.success(request, f"Album '{album_title}' has been deleted.")
        return redirect("user_albums_list", username=album_owner_username)

    # GET request - display confirmation page
    display_name = (
        album.owner.get_display_name()
        if hasattr(album.owner, "get_display_name")
        else album.owner.username
    )

    context = {
        "album": album,
        "profile_user": album.owner,
        "display_name": display_name,
    }

    return render(request, "images/album_delete_confirm.html", context)


@require_http_methods(["GET"])
def user_albums_api(request):
    """API endpoint to get user's albums as JSON"""
    if not request.user.is_authenticated:
        return JsonResponse({"albums": []})

    # Import Album here to avoid circular imports
    from .models import Album

    image_id = request.GET.get('image_id')

    albums = Album.objects.filter(owner=request.user).order_by('-created_at')

    albums_data = []
    for album in albums:
        album_dict = {
            'id': album.id,
            'title': album.title,
            'has_image': False
        }
        # Check if the image is in this album
        if image_id:
            album_dict['has_image'] = album.images.filter(id=image_id).exists()
        albums_data.append(album_dict)

    return JsonResponse({"albums": albums_data})


@require_http_methods(["POST"])
def add_image_to_album(request):
    """API endpoint to add an image to an existing album"""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)

    try:
        import json
        from .models import Album, AlbumImage

        data = json.loads(request.body)
        image_id = data.get('image_id')
        album_id = data.get('album_id')

        if not image_id or not album_id:
            return JsonResponse({"success": False, "error": "Missing image_id or album_id"}, status=400)

        image = get_object_or_404(Image, id=image_id)
        album = get_object_or_404(Album, id=album_id, owner=request.user)

        # Get the next order value
        max_order = album.album_images.aggregate(models.Max('order'))['order__max'] or 0
        next_order = max_order + 1

        # Add image to album
        album_image, created = AlbumImage.objects.get_or_create(
            album=album,
            image=image,
            defaults={'order': next_order}
        )

        if created:
            return JsonResponse({
                "success": True,
                "message": f"Image added to album '{album.title}'"
            })
        else:
            return JsonResponse({
                "success": True,
                "message": f"Image already in album '{album.title}'"
            })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@require_http_methods(["POST"])
def create_and_add_to_album(request):
    """API endpoint to create a new album and add an image to it"""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)

    try:
        import json
        from .models import Album, AlbumImage

        data = json.loads(request.body)
        image_id = data.get('image_id')
        album_title = data.get('album_title', '').strip()
        album_description = data.get('album_description', '').strip()
        album_public = data.get('album_public', False)

        if not image_id:
            return JsonResponse({"success": False, "error": "Missing image_id"}, status=400)

        if not album_title:
            return JsonResponse({"success": False, "error": "Album title is required"}, status=400)

        image = get_object_or_404(Image, id=image_id)

        # Create the album
        album = Album.objects.create(
            owner=request.user,
            title=album_title,
            description=album_description,
            public=album_public
        )

        # Add image to album
        AlbumImage.objects.create(
            album=album,
            image=image,
            order=1
        )

        return JsonResponse({
            "success": True,
            "message": f"Album '{album.title}' created and image added",
            "album_id": album.id
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@require_http_methods(["POST"])
def remove_image_from_album(request):
    """API endpoint to remove an image from an album"""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)

    try:
        import json
        from .models import Album, AlbumImage

        data = json.loads(request.body)
        image_id = data.get('image_id')
        album_id = data.get('album_id')

        if not image_id or not album_id:
            return JsonResponse({"success": False, "error": "Missing image_id or album_id"}, status=400)

        image = get_object_or_404(Image, id=image_id)
        album = get_object_or_404(Album, id=album_id, owner=request.user)

        # Remove image from album
        deleted_count, _ = AlbumImage.objects.filter(
            album=album,
            image=image
        ).delete()

        if deleted_count > 0:
            return JsonResponse({
                "success": True,
                "message": f"Image removed from album '{album.title}'"
            })
        else:
            return JsonResponse({
                "success": False,
                "error": "Image was not in this album"
            }, status=400)

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


def album_detail(request, display_name, album_id):
    """Display a specific album with its images"""
    from django.contrib.auth.models import User
    from .models import Album

    # Look up user by display name (first_name for OSM users or username)
    # Try first_name first (OSM username), then fall back to username
    user = get_object_or_404(User, first_name=display_name)
    if not user:
        user = get_object_or_404(User, username=display_name)
    album = get_object_or_404(Album, id=album_id, owner=user)

    # Check permissions - only show if public or user is viewing their own
    if not album.public and (not request.user.is_authenticated or request.user != user):
        raise Http404("Album not found")

    # Get images in album order
    album_images = album.album_images.select_related('image').order_by('order')

    # Calculate pending images count for the georeference button
    pending_images = sum(1 for ai in album_images if not ai.image.is_georeferenced)

    display_name = user.get_display_name() if hasattr(user, 'get_display_name') else user.username
    is_owner = request.user.is_authenticated and request.user == user

    context = {
        "album": album,
        "album_images": album_images,
        "profile_user": user,
        "display_name": display_name,
        "is_owner": is_owner,
        "pending_images": pending_images,
    }
    return render(request, "images/album_detail.html", context)


@require_http_methods(["POST"])
def toggle_album_public(request, album_id):
    """Toggle album public/private status (owner only)"""
    import json

    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )

    try:
        data = json.loads(request.body)
        new_public_status = data.get("public", True)
    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON"}, status=400
        )

    try:
        album = get_object_or_404(Album, id=album_id)
    except:
        return JsonResponse(
            {"success": False, "error": "Album not found"}, status=404
        )

    # Check that the user is the owner
    if album.owner != request.user:
        return JsonResponse(
            {"success": False, "error": "You don't have permission to modify this album"}, status=403
        )

    # Update the public status
    album.public = new_public_status
    album.save()

    return JsonResponse({
        "success": True,
        "public": album.public
    })


@require_http_methods(["POST"])
def mark_will_not_georef(request, image_id):
    """Mark an image as 'will not georeference' (admin only)"""
    # Check if user is authenticated and is staff
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )

    if not request.user.is_staff:
        return JsonResponse(
            {"success": False, "error": "Admin permissions required"}, status=403
        )

    image = get_object_or_404(Image, id=image_id)

    # Get the desired state from POST data, defaulting to True for backwards compatibility
    will_not_georef = request.POST.get("will_not_georef", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    image.will_not_georef = will_not_georef
    image.save(update_fields=["will_not_georef"])
    message = (
        'Image marked as "will not georeference"'
        if will_not_georef
        else 'Removed "will not georeference" flag'
    )

    return JsonResponse({"success": True, "message": message})


def get_random_image(request):
    """Get a random image for georeferencing"""
    # Get images that haven't been georeferenced and aren't marked as will_not_georef
    # Exclude duplicate images from being suggested
    available_images = Image.objects.filter(
        georeferences__isnull=True,
        will_not_georef=False,
        duplicate_of__isnull=True,
        collection__public=True,
        collection__source__public=True,
    )

    # Note: We deliberately do NOT exclude skipped images - users should be able to
    # go back and georeference images they previously skipped

    # Filter by difficulty if specified
    difficulty = request.GET.get("difficulty")
    if difficulty in ["easy", "medium", "hard"]:
        available_images = available_images.filter(difficulty=difficulty)

    # Get a random image
    image = available_images.order_by("?").first()

    if image:
        return redirect("images:image_detail", image_id=image.id)
    else:
        messages.info(
            request,
            "No more images available for georeferencing with your current filters.",
        )
        return redirect("images:image_list")


def image_stats(request):
    """Display statistics about the georeferencing progress"""
    # Only show stats for public sources/collections
    public_images = Image.objects.filter(
        collection__public=True, collection__source__public=True
    )

    total_images = public_images.count()
    georeferenced_images = (
        public_images.filter(georeferences__isnull=False).distinct().count()
    )
    will_not_georef_images = public_images.filter(will_not_georef=True).count()
    pending_images = total_images - georeferenced_images - will_not_georef_images

    difficulty_stats = {
        "easy": public_images.filter(difficulty="easy").count(),
        "medium": public_images.filter(difficulty="medium").count(),
        "hard": public_images.filter(difficulty="hard").count(),
        "unrated": public_images.filter(difficulty__isnull=True).count(),
    }

    context = {
        "total_images": total_images,
        "georeferenced_images": georeferenced_images,
        "will_not_georef_images": will_not_georef_images,
        "pending_images": pending_images,
        "difficulty_stats": difficulty_stats,
        "completion_percentage": (georeferenced_images / total_images * 100)
        if total_images > 0
        else 0,
    }

    return render(request, "images/stats.html", context)


def search_page(request):
    """Display the semantic search interface"""
    all_subjects = Subject.objects.all().values("id", "title")
    context = {
        "clip_available": CLIP_AVAILABLE,
        "all_subjects_json": json.dumps(list(all_subjects)),
    }
    return render(request, "images/search.html", context)


def geojson_endpoint(request):
    """Return GeoJSON FeatureCollection of georeferenced images"""

    # Start with all georeferenced images from public collections/sources
    images = (
        Image.objects.select_related("collection__source")
        .prefetch_related("georeferences", "subject_mappings__subject__wikidata_item")
        .filter(
            georeferences__isnull=False,  # Must be georeferenced
            collection__public=True,  # Collection must be public
            collection__source__public=True,  # Source must be public
        )
    )

    # Apply filters based on GET parameters
    image_id = request.GET.get("image")
    collection_id = request.GET.get("collection")
    source_id = request.GET.get("source")
    subject_id = request.GET.get("subject")

    if image_id:
        images = images.filter(id=image_id)
    if collection_id:
        images = images.filter(collection_id=collection_id)
    if source_id:
        images = images.filter(collection__source_id=source_id)
    if subject_id:
        images = images.filter(subject_mappings__subject_id=subject_id)

    # Build GeoJSON features
    features = []
    for image in images:
        georeference = image.get_georeference()
        if not georeference:  # Skip if no georeference found
            continue

        # Build the image entry URL (absolute URL to image detail page)
        img_entry = request.build_absolute_uri(
            reverse("images:image_detail", kwargs={"image_id": image.id})
        )

        # Build properties
        properties = {
            "img_url": image.permalink,
            "img_entry": img_entry,
            "original_date": str(image.original_date) if image.original_date else None,
            "edtf_date": str(image.edtf_date) if image.edtf_date else None,
            "start_decdate": image.start_decdate,
            "fuzzy_start_decdate": image.fuzzy_start_decdate,
            "end_decdate": image.end_decdate,
            "fuzzy_end_decdate": image.fuzzy_end_decdate,
        }

        # Only include direction if it's not None
        if georeference.direction is not None:
            properties["direction"] = georeference.direction

        # Only include scale if it's not None
        if image.scale is not None:
            properties["scale"] = image.scale

        # Add subjects as Wikidata IDs if they exist
        subject_wikidata_ids = [
            mapping.subject.wikidata_item.wikidata_id
            for mapping in image.subject_mappings.all()
            if mapping.subject.wikidata_item
        ]
        if subject_wikidata_ids:
            properties["subjects"] = subject_wikidata_ids

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [georeference.point.x, georeference.point.y],
            },
            "properties": properties,
        }
        features.append(feature)

    # Build final GeoJSON
    geojson = {"type": "FeatureCollection", "features": features}

    return JsonResponse(geojson)


def vector_tiles_endpoint(request, z, x, y):
    """Return MVT vector tiles of georeferenced images (using materialized view for performance)"""
    from django.db import connection

    enable_scale_filter = (
        request.GET.get("enable_scale_filter", "false").lower() == "true"
    )

    # Apply the same filters as GeoJSON endpoint
    image_id = request.GET.get("image")
    collection_id = request.GET.get("collection")
    source_id = request.GET.get("source")
    subject_id = request.GET.get("subject")

    # Build WHERE conditions for filtering on pre-filtered materialized view
    where_conditions = []
    where_params = []

    if enable_scale_filter:
        min_scale = get_min_scale_for_zoom(z)
        if min_scale is not None:
            where_conditions.append("(scale >= %s OR scale = 0)")
            where_params.append(min_scale)

    if image_id:
        where_conditions.append("image_id = %s")
        where_params.append(image_id)
    if collection_id:
        where_conditions.append(
            "image_id IN (SELECT id FROM images_image WHERE collection_id = %s)"
        )
        where_params.append(collection_id)
    if source_id:
        where_conditions.append(
            "image_id IN (SELECT i.id FROM images_image i JOIN images_collection c ON i.collection_id = c.id WHERE c.source_id = %s)"
        )
        where_params.append(source_id)
    if subject_id:
        where_conditions.append(
            "image_id IN (SELECT image_id FROM images_subjectmapping WHERE subject_id = %s)"
        )
        where_params.append(subject_id)

    where_clause = " AND ".join(where_conditions)

    # Build WHERE clause - add filter conditions if any exist
    if where_clause:
        where_clause_sql = f"WHERE {where_clause} AND ST_Intersects(point, ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326))"
    else:
        where_clause_sql = "WHERE ST_Intersects(point, ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326))"

    sql = f"""
        SELECT ST_AsMVT(mvtgeoms.*, 'image_points') as mvt FROM (
            SELECT
                ST_AsMVTGeom(point_3857, ST_TileEnvelope(%s, %s, %s)) AS geom,
                image_id as id,
                img_url,
                original_date,
                edtf_date,
                start_decdate,
                fuzzy_start_decdate,
                end_decdate,
                fuzzy_end_decdate,
                scale,
                direction,
                confidence
            FROM public_georeferences_mvt
            {where_clause_sql}
        ) mvtgeoms
    """

    # Parameters: Z, X, Y for tile envelope (twice), plus any filter parameters
    query_params = [z, x, y] + where_params + [z, x, y]

    with connection.cursor() as cursor:
        cursor.execute(sql, query_params)
        result = cursor.fetchone()

        if result and result[0]:
            mvt_data = bytes(result[0])
            response = HttpResponse(mvt_data, content_type="application/x-protobuf")
            return response
        else:
            return HttpResponse(b"", content_type="application/x-protobuf")


def map_layers_view(request):
    """Return all map layers organized by collections in a single object"""
    collections = LayerCollection.objects.prefetch_related("layers").all()

    collections_data = []
    for collection in collections:
        collection_data = {
            "name": collection.name,
            "description": collection.description,
            "layers": [],
        }

        for layer in collection.layers.all():
            layer_data = {
                "name": layer.name,
                "type": layer.type,
                "url": layer.url,
            }

            # Add optional fields if they exist
            if layer.attribution:
                layer_data["attribution"] = layer.attribution
            if layer.description:
                layer_data["description"] = layer.description

            collection_data["layers"].append(layer_data)

        collections_data.append(collection_data)

    # Return single object with all metadata
    response_data = {"collections": collections_data}

    return JsonResponse(response_data)


# Global variables for CLIP model (loaded on first use)
_clip_model = None
_clip_preprocess = None
_clip_device = None


def _load_clip_model():
    """Load CLIP model on first use"""
    global _clip_model, _clip_preprocess, _clip_device

    if _clip_model is not None:
        return _clip_model, _clip_preprocess, _clip_device

    if not CLIP_AVAILABLE:
        raise ImportError(
            "CLIP dependencies not available. Install torch and openai-clip."
        )

    # Determine device
    _clip_device = "cuda" if torch.cuda.is_available() else "cpu"

    model_name = "ViT-L/14@336px"
    local_model_dir = Path("./models").absolute()

    # Download model if it doesn't exist
    from django.core.management import call_command
    try:
        call_command(
            "download_clip_model",
            model_name=model_name,
            device=_clip_device,
            verbosity=0,  # Suppress output
        )
    except Exception:
        # If download command fails, continue anyway - clip.load will handle it
        pass

    # Load from local directory
    _clip_model, _clip_preprocess = clip.load(
        model_name, device=_clip_device, download_root=local_model_dir
    )

    return _clip_model, _clip_preprocess, _clip_device


def _get_text_embedding(text):
    """Generate embedding for text query"""
    model, preprocess, device = _load_clip_model()

    with torch.no_grad():
        text_input = clip.tokenize([text]).to(device)
        text_features = model.encode_text(text_input)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    return text_features.cpu().numpy()[0].tolist()


@require_http_methods(["GET", "POST"])
def semantic_search(request):
    """API endpoint for semantic search using CLIP embeddings"""
    if not CLIP_AVAILABLE:
        return JsonResponse(
            {
                "success": False,
                "error": "Semantic search not available. CLIP dependencies not installed.",
            },
            status=503,
        )

    # Get search query
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            query = data.get("query", "").strip()
        except json.JSONDecodeError:
            return JsonResponse(
                {"success": False, "error": "Invalid JSON in request body"}, status=400
            )
    else:  # GET request
        query = request.GET.get("q", "").strip()

    if not query:
        return JsonResponse(
            {
                "success": False,
                "error": "Query parameter 'q' (GET) or 'query' (POST) is required",
            },
            status=400,
        )

    # Get search and pagination parameters
    limit = min(int(request.GET.get("pagelimit", 20)), 100)
    page = int(request.GET.get("page", 1))
    if page < 1:
        page = 1
    offset = (page - 1) * limit

    include_no_embedding = (
        request.GET.get("include_no_embedding", "false").lower() == "true"
    )
    georeferenced_only = (
        request.GET.get("georeferenced_only", "false").lower() == "true"
    )
    non_georeferenced_only = (
        request.GET.get("non_georeferenced_only", "false").lower() == "true"
    )

    # Year filtering parameters
    start_year = request.GET.get("start_year")
    end_year = request.GET.get("end_year")

    # Validate year parameters
    if start_year:
        try:
            start_year = int(start_year)
        except ValueError:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid start_year parameter. Must be an integer.",
                },
                status=400,
            )

    if end_year:
        try:
            end_year = int(end_year)
        except ValueError:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid end_year parameter. Must be an integer.",
                },
                status=400,
            )

    # Subject filtering parameters
    with_subjects_str = request.GET.get("with_subjects")
    without_subjects_str = request.GET.get("without_subjects")
    no_subjects = request.GET.get("no_subjects", "false").lower() == "true"

    with_subject_ids = []
    if with_subjects_str:
        try:
            with_subject_ids = [
                int(s_id) for s_id in with_subjects_str.split(",") if s_id.strip()
            ]
        except ValueError:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid with_subjects parameter. Must be comma-separated integers.",
                },
                status=400,
            )

    without_subject_ids = []
    if without_subjects_str:
        try:
            without_subject_ids = [
                int(s_id) for s_id in without_subjects_str.split(",") if s_id.strip()
            ]
        except ValueError:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid without_subjects parameter. Must be comma-separated integers.",
                },
                status=400,
            )

    try:
        # First, detect the dimension of existing embeddings in the database
        sample_embedding = None
        expected_dimension = None

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT embedding
                FROM images_image
                WHERE embedding IS NOT NULL
                AND id IN (
                    SELECT i.id
                    FROM images_image i
                    JOIN images_collection c ON i.collection_id = c.id
                    JOIN images_source s ON c.source_id = s.id
                    WHERE c.public = true AND s.public = true
                )
                LIMIT 1
            """)
            result = cursor.fetchone()
            if result:
                sample_embedding = result[0]
                expected_dimension = len(sample_embedding)

        # Generate query embedding
        query_embedding = _get_text_embedding(query)
        query_dimension = len(query_embedding)

        # Check dimension compatibility
        if expected_dimension and query_dimension != expected_dimension:
            return JsonResponse(
                {
                    "success": False,
                    "error": f"Model dimension mismatch. Database contains {expected_dimension}D embeddings, but current model produces {query_dimension}D embeddings. Please regenerate embeddings with the current model.",
                },
                status=400,
            )

        # Use raw SQL for vector similarity search
        # Note: This requires pgvector extension to be installed

        with connection.cursor() as cursor:
            # Convert embedding to PostgreSQL array format
            embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

            # Build dynamic WHERE conditions and separate parameters
            where_conditions = ["embedding IS NOT NULL"]
            where_params = []

            # Add georeferenced filter
            if georeferenced_only:
                where_conditions.append(
                    "EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"
                )
            elif non_georeferenced_only:
                where_conditions.append(
                    "NOT EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"
                )

            # Add year filtering conditions
            if start_year is not None:
                where_conditions.append(
                    "(start_decdate >= %s OR fuzzy_start_decdate >= %s)"
                )
                where_params.extend([start_year, start_year])

            if end_year is not None:
                where_conditions.append(
                    "(end_decdate <= %s OR fuzzy_end_decdate <= %s)"
                )
                where_params.extend([end_year, end_year])

            # Add subject filtering conditions
            if no_subjects:
                where_conditions.append(
                    "NOT EXISTS (SELECT 1 FROM images_subjectmapping sm WHERE sm.image_id = images_image.id)"
                )
            else:
                if with_subject_ids:
                    for subject_id in with_subject_ids:
                        where_conditions.append(
                            "EXISTS (SELECT 1 FROM images_subjectmapping sm WHERE sm.image_id = images_image.id AND sm.subject_id = %s)"
                        )
                        where_params.append(subject_id)

                if without_subject_ids:
                    where_conditions.append(
                        "images_image.id NOT IN (SELECT image_id FROM images_subjectmapping WHERE subject_id = ANY(%s))"
                    )
                    where_params.append(without_subject_ids)

            # Combine all WHERE conditions
            where_clause = " AND ".join(where_conditions)

            # Get total count for pagination
            count_sql = f"""
                SELECT COUNT(images_image.id)
                FROM images_image
                WHERE {where_clause}
                AND id IN (
                    SELECT i.id
                    FROM images_image i
                    JOIN images_collection c ON i.collection_id = c.id
                    JOIN images_source s ON c.source_id = s.id
                    WHERE c.public = true AND s.public = true AND i.duplicate_of_id IS NULL
                )
            """
            cursor.execute(count_sql, where_params)
            total_count = cursor.fetchone()[0]

            # Raw SQL query for cosine similarity
            sql = f"""
                SELECT
                    id,
                    title,
                    permalink,
                    original_date,
                    edtf_date,
                    start_decdate,
                    end_decdate,
                    (embedding::vector <=> %s::vector) as distance
                FROM images_image
                WHERE {where_clause}
                AND id IN (
                    SELECT i.id
                    FROM images_image i
                    JOIN images_collection c ON i.collection_id = c.id
                    JOIN images_source s ON c.source_id = s.id
                    WHERE c.public = true AND s.public = true AND i.duplicate_of_id IS NULL
                )
                ORDER BY embedding::vector <=> %s::vector
                LIMIT %s
                OFFSET %s
            """

            query_params = (
                [embedding_str] + where_params + [embedding_str, limit, offset]
            )

            cursor.execute(sql, query_params)
            results = cursor.fetchall()

        # Format results
        search_results = []
        for row in results:
            (
                image_id,
                title,
                permalink,
                original_date,
                edtf_date,
                start_decdate,
                end_decdate,
                distance,
            ) = row

            # Get the full image object for additional data
            try:
                image = Image.objects.select_related("collection__source").get(
                    id=image_id
                )

                result = {
                    "id": image_id,
                    "title": title,
                    "permalink": permalink,
                    "original_date": str(original_date) if original_date else None,
                    "edtf_date": str(edtf_date) if edtf_date else None,
                    "distance": float(distance),
                    "similarity": 1.0
                    - float(distance),  # Convert distance to similarity
                    "collection": {
                        "name": image.collection.name,
                        "slug": image.collection.slug,
                    },
                    "source": {
                        "name": image.collection.source.name,
                        "slug": image.collection.source.slug,
                    },
                    "detail_url": f"/{image_id}/",
                    "georeferenced": image.is_georeferenced,
                    "will_not_georef": image.will_not_georef,
                }

                # Add georeference data if available
                if image.is_georeferenced:
                    georeference = image.get_georeference()
                    if georeference:
                        result["georeference"] = {
                            "latitude": georeference.point.y,
                            "longitude": georeference.point.x,
                            "direction": georeference.direction,
                            "confidence": georeference.confidence,
                        }

                search_results.append(result)

            except Image.DoesNotExist:
                # Skip if image was deleted between query and retrieval
                continue

        return JsonResponse(
            {
                "success": True,
                "query": query,
                "results": search_results,
                "count": total_count,
                "page": page,
                "limit": limit,
            }
        )

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Search failed: {str(e)}"}, status=500
        )


def find_similar_images(request, image_id):
    """
    Find and display images with embeddings most similar to a given image.
    Supports filtering by georeferenced status via query parameter.
    """
    if not CLIP_AVAILABLE:
        messages.error(
            request,
            "Similarity search is not available. CLIP dependencies not installed.",
        )
        return redirect("images:image_detail", image_id=image_id)

    # Get the target image and its embedding
    target_image = get_object_or_404(Image, id=image_id)
    if not target_image.embedding:
        messages.error(
            request,
            "The selected image does not have an embedding, so similar images cannot be found.",
        )
        return redirect("images:image_detail", image_id=image_id)

    # Get georeferenced filter from query parameter
    georeferenced_status = request.GET.get("georeferenced", "all")  # 'all', 'yes', or 'none'

    from django.db import connection

    try:
        with connection.cursor() as cursor:
            # Convert embedding to PostgreSQL array format
            embedding_str = "[" + ",".join(map(str, target_image.embedding)) + "]"

            # Build WHERE conditions based on georeferenced filter
            georeference_condition = ""
            if georeferenced_status == "yes":
                georeference_condition = "AND EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"
            elif georeferenced_status == "none":
                georeference_condition = "AND NOT EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"

            # Raw SQL query for cosine similarity to get all similar images
            sql = f"""
                SELECT
                    id,
                    (embedding::vector <=> %s::vector) as distance
                FROM images_image
                WHERE embedding IS NOT NULL
                AND id != %s
                {georeference_condition}
                AND id IN (
                    SELECT i.id
                    FROM images_image i
                    JOIN images_collection c ON i.collection_id = c.id
                    JOIN images_source s ON c.source_id = s.id
                    WHERE c.public = true AND s.public = true AND i.duplicate_of_id IS NULL
                )
                ORDER BY distance
            """
            cursor.execute(sql, [embedding_str, target_image.id])
            all_results = cursor.fetchall()

        # Get a list of all similar image IDs, ordered by similarity
        all_similar_ids = [row[0] for row in all_results]

        # Paginate the full list of IDs
        paginator = Paginator(all_similar_ids, 24)  # 24 images per page
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        # Get the full Image objects for the current page
        current_page_ids = page_obj.object_list
        images_on_page = Image.objects.filter(id__in=current_page_ids).select_related(
            "collection__source"
        )

        # Create a dictionary to map IDs to image objects for correct ordering
        images_by_id = {img.id: img for img in images_on_page}

        # Re-order the fetched image objects based on the paginated ID list
        ordered_images_on_page = [
            images_by_id[img_id]
            for img_id in current_page_ids
            if img_id in images_by_id
        ]

        # Replace the list of IDs in the page object with the actual image objects
        page_obj.object_list = ordered_images_on_page

        context = {
            "target_image": target_image,
            "page_obj": page_obj,
            "total_similar_count": paginator.count,
            "georeferenced_status": georeferenced_status,
        }

        return render(request, "images/similar_images.html", context)

    except Exception as e:
        messages.error(
            request, f"An error occurred while finding similar images: {str(e)}"
        )
        return redirect("images:image_detail", image_id=image_id)


class WordSimilarity(Func):
    function = "word_similarity"
    arity = 2


def _generate_highlighted_snippet(text, query, max_length=200):
    """
    Generate a highlighted snippet from text based on query terms.
    Returns a dict with highlighted text and snippet.
    """
    if not text or not query:
        return {"snippet": text[:max_length] if text else "", "highlighted": text or ""}

    import re

    # Split query into individual terms
    query_terms = [term.strip().lower() for term in query.split() if term.strip()]
    if not query_terms:
        return {"snippet": text[:max_length], "highlighted": text}

    # Create regex pattern for highlighting (case insensitive)
    pattern = "|".join(re.escape(term) for term in query_terms)

    # Find the best snippet position (around first match)
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        start_pos = max(0, match.start() - max_length // 3)
        end_pos = min(len(text), start_pos + max_length)
        snippet = text[start_pos:end_pos]

        # Add ellipsis if needed
        if start_pos > 0:
            snippet = "..." + snippet
        if end_pos < len(text):
            snippet = snippet + "..."
    else:
        snippet = text[:max_length]

    # Highlight matching terms in both snippet and full text
    def highlight_replacer(match):
        return f"<mark>{match.group(0)}</mark>"

    highlighted_snippet = re.sub(
        pattern, highlight_replacer, snippet, flags=re.IGNORECASE
    )
    highlighted_full = re.sub(pattern, highlight_replacer, text, flags=re.IGNORECASE)

    return {"snippet": highlighted_snippet, "highlighted": highlighted_full}


@require_http_methods(["GET", "POST"])
def text_search(request):
    """API endpoint for text search using PostgreSQL trigram word similarity."""
    if not HAS_POSTGRES_SEARCH:
        return JsonResponse(
            {
                "success": False,
                "error": "Text search not available. PostgreSQL search dependencies not installed.",
            },
            status=503,
        )

    # Get search query
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            query = data.get("query", "").strip()
        except json.JSONDecodeError:
            return JsonResponse(
                {"success": False, "error": "Invalid JSON in request body"}, status=400
            )
    else:  # GET request
        query = request.GET.get("q", "").strip()

    # Get search and pagination parameters
    limit = min(int(request.GET.get("pagelimit", 20)), 100)
    page = int(request.GET.get("page", 1))
    if page < 1:
        page = 1
    offset = (page - 1) * limit
    georeferenced_only = (
        request.GET.get("georeferenced_only", "false").lower() == "true"
    )
    non_georeferenced_only = (
        request.GET.get("non_georeferenced_only", "false").lower() == "true"
    )
    # Distance is 1 - similarity. A lower distance is a better match.
    distance_threshold = float(request.GET.get("threshold", 0.7))

    # Year filtering parameters
    start_year = request.GET.get("start_year")
    end_year = request.GET.get("end_year")

    # Subject filtering parameters
    with_subjects_str = request.GET.get("with_subjects")
    without_subjects_str = request.GET.get("without_subjects")
    no_subjects = request.GET.get("no_subjects", "false").lower() == "true"

    if not query and not any([with_subjects_str, without_subjects_str, no_subjects]):
        return JsonResponse(
            {
                "success": False,
                "error": "A search query or subject filter is required.",
            },
            status=400,
        )

    with_subject_ids = []
    if with_subjects_str:
        try:
            with_subject_ids = [
                int(s_id) for s_id in with_subjects_str.split(",") if s_id.strip()
            ]
        except ValueError:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid with_subjects parameter. Must be comma-separated integers.",
                },
                status=400,
            )

    without_subject_ids = []
    if without_subjects_str:
        try:
            without_subject_ids = [
                int(s_id) for s_id in without_subjects_str.split(",") if s_id.strip()
            ]
        except ValueError:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid without_subjects parameter. Must be comma-separated integers.",
                },
                status=400,
            )

    # --- Start of Query Logic ---
    try:
        # 1. Use the ORM for initial filtering (easier for optional filters)
        images = (
            Image.objects.filter(
                collection__public=True,
                collection__source__public=True,
                duplicate_of__isnull=True,
            )
            .select_related("collection__source")
            .prefetch_related("georeferences")
        )

        if georeferenced_only:
            images = images.filter(georeferences__isnull=False).distinct()
        elif non_georeferenced_only:
            images = images.filter(georeferences__isnull=True)

        if start_year:
            try:
                images = images.filter(
                    models.Q(start_decdate__gte=int(start_year))
                    | models.Q(fuzzy_start_decdate__gte=int(start_year))
                )
            except ValueError:
                return JsonResponse(
                    {"success": False, "error": "Invalid start_year"}, status=400
                )

        if end_year:
            try:
                images = images.filter(
                    models.Q(end_decdate__lte=int(end_year))
                    | models.Q(fuzzy_end_decdate__lte=int(end_year))
                )
            except ValueError:
                return JsonResponse(
                    {"success": False, "error": "Invalid end_year"}, status=400
                )

        # Add subject filtering
        if no_subjects:
            images = images.filter(subjects__isnull=True)
        else:
            if with_subject_ids:
                for subject_id in with_subject_ids:
                    images = images.filter(subjects__id=subject_id)

            if without_subject_ids:
                images = images.exclude(subjects__id__in=without_subject_ids)

        # Handle case where there is no text query (filter-only search)
        if not query:
            paginator = Paginator(images.distinct().order_by("id"), limit)
            page_obj = paginator.get_page(page)
            search_results = []
            for image in page_obj.object_list:
                result = {
                    "id": image.id,
                    "title": image.title,
                    "permalink": image.permalink,
                    "original_date": str(image.original_date)
                    if image.original_date
                    else None,
                    "edtf_date": str(image.edtf_date) if image.edtf_date else None,
                    "collection": {
                        "name": image.collection.name,
                        "slug": image.collection.slug,
                    },
                    "source": {
                        "name": image.collection.source.name,
                        "slug": image.collection.source.slug,
                    },
                    "detail_url": f"/{image.id}/",
                    "georeferenced": image.is_georeferenced,
                    "will_not_georef": image.will_not_georef,
                }
                search_results.append(result)

            return JsonResponse(
                {
                    "success": True,
                    "query": query,
                    "results": search_results,
                    "count": paginator.count,
                    "page": page,
                    "limit": limit,
                    "search_type": "filter_only",
                }
            )

        # --- Text search logic for when a query is present ---
        filtered_ids = list(images.values_list("id", flat=True))

        if not filtered_ids:
            return JsonResponse(
                {
                    "success": True,
                    "query": query,
                    "results": [],
                    "count": 0,
                    "page": page,
                    "limit": limit,
                }
            )

        # 2. Use Raw SQL for the complex trigram query for performance and control
        from django.db import connection

        with connection.cursor() as cursor:
            # First, get total count of results that meet the threshold
            count_sql = """
                SELECT COUNT(id)
                FROM images_image
                WHERE
                    id = ANY(%(ids)s)
                    AND LEAST(
                        COALESCE(%(query)s <<-> title, 1.0),
                        COALESCE(%(query)s <<-> description, 1.0)
                    ) < %(threshold)s
            """
            count_params = {
                "query": query,
                "ids": filtered_ids,
                "threshold": distance_threshold,
            }
            cursor.execute(count_sql, count_params)
            total_count = cursor.fetchone()[0]

            # Now, get the paginated results
            sql = """
                SELECT
                    id, title, permalink, original_date, edtf_date,
                    LEAST(
                        COALESCE(%(query)s <<-> title, 1.0),
                        COALESCE(%(query)s <<-> description, 1.0)
                    ) as distance
                FROM
                    images_image
                WHERE
                    id = ANY(%(ids)s)
                    AND LEAST(
                        COALESCE(%(query)s <<-> title, 1.0),
                        COALESCE(%(query)s <<-> description, 1.0)
                    ) < %(threshold)s
                ORDER BY
                    distance ASC
                LIMIT %(limit)s
                OFFSET %(offset)s
            """
            params = {
                "query": query,
                "ids": filtered_ids,
                "threshold": distance_threshold,
                "limit": limit,
                "offset": offset,
            }
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        # 3. Format the results
        search_results = []
        image_ids = [row[0] for row in rows]
        images_by_id = {
            img.id: img
            for img in Image.objects.filter(id__in=image_ids).select_related(
                "collection__source"
            )
        }

        for row in rows:
            # Unpack row data
            image_id, title, permalink, original_date, edtf_date, distance = row
            image = images_by_id.get(image_id)

            if not image:
                continue

            result = {
                "id": image_id,
                "title": title,
                "permalink": permalink,
                "original_date": str(original_date) if original_date else None,
                "edtf_date": str(edtf_date) if edtf_date else None,
                "similarity": 1.0
                - float(distance),  # Convert distance back to similarity
                "collection": {
                    "name": image.collection.name,
                    "slug": image.collection.slug,
                },
                "source": {
                    "name": image.collection.source.name,
                    "slug": image.collection.source.slug,
                },
                "detail_url": f"/{image.id}/",
                "georeferenced": image.is_georeferenced,
                "will_not_georef": image.will_not_georef,
            }
            search_results.append(result)

        return JsonResponse(
            {
                "success": True,
                "query": query,
                "results": search_results,
                "count": total_count,
                "page": page,
                "limit": limit,
                "search_type": "word_distance",
            }
        )

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Text search failed: {str(e)}"}, status=500
        )


def subject_autocomplete(request):
    if "q" not in request.GET:
        return JsonResponse([], safe=False)

    query = request.GET.get("q", "")
    if len(query) < 2:  # Don't search for very short strings
        return JsonResponse([], safe=False)

    subjects = (
        Subject.objects.filter(title__icontains=query)
        .annotate(lower_title=Lower("title"))
        .order_by("lower_title")[:10]
    )

    results = []
    for subject in subjects:
        result = {
            "id": subject.id,
            "title": subject.title,
            "description": subject.description,
            "wikidata_id": subject.wikidata_item.wikidata_id
            if subject.wikidata_item
            else None,
        }
        results.append(result)

    return JsonResponse(results, safe=False)


@require_http_methods(["POST"])
def add_subject_to_image(request, image_id):
    """Add a subject to an image via Wikidata ID (logged-in users only)"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "You must be logged in to edit subjects"},
            status=403,
        )

    image = get_object_or_404(Image, id=image_id)

    try:
        data = json.loads(request.body)
        wikidata_id = data.get("wikidata_id", "").strip()

        if not wikidata_id or not wikidata_id.startswith("Q"):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid Wikidata ID format. Must start with 'Q'.",
                },
                status=400,
            )

        # The new model logic handles fetching on creation.
        # We wrap this in a try-except block to catch validation errors if fetching fails.
        try:
            wikidata_item, created = WikidataItem.objects.get_or_create(
                wikidata_id=wikidata_id
            )
        except ValidationError as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

        # Try to get or create Subject
        subject, subject_created = Subject.objects.get_or_create(
            wikidata_item=wikidata_item,
            defaults={
                "title": wikidata_item.title,
                "description": wikidata_item.description
                or f"Subject from Wikidata: {wikidata_id}",
            },
        )

        # Update Subject if it exists but has outdated info
        if not subject_created and (
            subject.title == wikidata_id or not subject.description
        ):
            subject.title = wikidata_item.title
            subject.description = (
                wikidata_item.description or f"Subject from Wikidata: {wikidata_id}"
            )
            subject.save()

        if SubjectMapping.objects.filter(image=image, subject=subject).exists():
            return JsonResponse(
                {
                    "success": False,
                    "error": "This subject is already associated with this image.",
                },
                status=400,
            )

        max_order = (
            SubjectMapping.objects.filter(image=image).aggregate(
                max_order=models.Max("order")
            )["max_order"]
            or 0
        )

        subject_mapping = SubjectMapping.objects.create(
            image=image, subject=subject, order=max_order + 1
        )

        return JsonResponse(
            {
                "success": True,
                "message": f"Subject {wikidata_id} added to image",
                "subject": {
                    "id": subject.id,
                    "title": subject.title,
                    "description": subject.description,
                    "wikidata_id": wikidata_id,
                    "wikidata_url": wikidata_item.wikidata_url,
                    "image_url": wikidata_item.image_url,
                    "relation_id": subject_mapping.id,
                    "url": subject.get_absolute_url(),
                },
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON in request body"}, status=400
        )
    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Error adding subject: {str(e)}"}, status=500
        )


@require_http_methods(["POST"])
def remove_subject_from_image(request, subject_mapping_id):
    """Remove a subject from an image (logged-in users only)"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "You must be logged in to edit subjects"},
            status=403,
        )

    try:
        # Find the specific subject mapping by its ID
        subject_relation = get_object_or_404(SubjectMapping, id=subject_mapping_id)
        subject_title = subject_relation.subject.title

        # Although we're not using the image for lookup, it's good practice
        # to ensure it exists, though get_object_or_404 handles this implicitly.
        # image = subject_relation.image

        subject_relation.delete()

        return JsonResponse(
            {
                "success": True,
                "message": f"Subject '{subject_title}' removed from image.",
            }
        )
    except SubjectMapping.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": "Subject mapping not found."}, status=404
        )
    except Exception:
        # Log the exception for debugging
        # logger.error(f"Error removing subject mapping: {e}")
        return JsonResponse(
            {"success": False, "error": "An unexpected error occurred."},
            status=500,
        )


@require_http_methods(["POST"])
def reorder_subjects(request, image_id):
    """API endpoint to reorder subjects for an image (logged-in users only)"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "You must be logged in to edit subjects"},
            status=403,
        )

    image = get_object_or_404(Image, id=image_id)

    try:
        data = json.loads(request.body)
        ordered_ids = data.get("order")

        if not isinstance(ordered_ids, list):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid data format: 'order' must be a list.",
                },
                status=400,
            )

        with transaction.atomic():
            # Get all subject relations for this image
            subject_relations = SubjectMapping.objects.filter(image=image)

            # Create a map of ID to instance
            relation_map = {
                str(relation.id): relation for relation in subject_relations
            }

            # Check if the received IDs match the existing relations
            if set(relation_map.keys()) != set(ordered_ids):
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Submitted subject IDs do not match existing subjects for this image.",
                    },
                    status=400,
                )

            # Update the order field based on the new order
            for index, subject_relation_id in enumerate(ordered_ids):
                relation = relation_map.get(str(subject_relation_id))
                if relation:
                    relation.order = index
                    relation.save(update_fields=["order"])

        return JsonResponse(
            {"success": True, "message": "Subject order updated successfully."}
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON in request body"}, status=400
        )
    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"An unexpected error occurred: {str(e)}"},
            status=500,
        )


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
    context = {
        "page_obj": page_obj,
        "overall_stats": overall_stats,
    }
    return render(request, "images/browse_subjects.html", context)


def subject_detail(request, subject_slug):
    """Detail view for a specific subject showing its images"""
    subject = get_object_or_404(Subject, slug=subject_slug)

    # Get images associated with this subject (only from public collections, excluding duplicates)
    images = (
        Image.objects.filter(
            subject_mappings__subject=subject,
            duplicate_of__isnull=True,
            collection__public=True,
            collection__source__public=True,
        )
        .select_related("collection__source")
        .annotate(
            has_georeference=Case(
                When(georeferences__isnull=False, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("will_not_georef", "has_georeference", "id")
        .distinct()
    )

    total_images = images.count()
    georeferenced_images = images.filter(georeferences__isnull=False).distinct().count()
    pending_images = total_images - georeferenced_images

    # Paginate images for browsing
    paginator = Paginator(images, 24)  # 24 images per page for grid layout
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "subject": subject,
        "page_obj": page_obj,
        "total_images": total_images,
        "georeferenced_images": georeferenced_images,
        "pending_images": pending_images,
        "completion_percentage": (georeferenced_images / total_images * 100)
        if total_images > 0
        else 0,
    }
    return render(request, "images/subject_detail.html", context)


@staff_member_required
def label_scales(request):
    """
    Admin interface for labeling the scale of images.
    Can be filtered by a search query.
    """
    georeferenced_only = (
        request.GET.get("georeferenced_only", "false").lower() == "true"
    )
    query = request.GET.get("q", "").strip()
    search_type = request.GET.get("search_type", "text")  # 'text' or 'semantic'

    # Start with images that need scale labeling
    images = Image.objects.filter(scale__isnull=True)

    if georeferenced_only:
        images = images.filter(georeferences__isnull=False).distinct()

    if query:
        if search_type == "semantic" and CLIP_AVAILABLE:
            try:
                from django.db import connection

                query_embedding = _get_text_embedding(query)
                embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
                base_image_ids = list(images.values_list("id", flat=True))

                if not base_image_ids:
                    images = Image.objects.none()
                else:
                    with connection.cursor() as cursor:
                        # Find images with embeddings and order by similarity
                        sql = """
                            SELECT id, (embedding::vector <=> %s::vector) as distance
                            FROM images_image
                            WHERE id = ANY(%s) AND embedding IS NOT NULL
                            ORDER BY distance
                        """
                        cursor.execute(sql, [embedding_str, base_image_ids])
                        result_ids = [row[0] for row in cursor.fetchall()]

                    if not result_ids:
                        images = Image.objects.none()
                    else:
                        # Preserve the search order
                        preserved_order = Case(
                            *[
                                When(pk=pk, then=pos)
                                for pos, pk in enumerate(result_ids)
                            ]
                        )
                        images = Image.objects.filter(id__in=result_ids).order_by(
                            preserved_order
                        )

            except Exception:  # Broad exception to avoid crashing the admin page
                # Could log this error
                images = images.order_by("id")  # Fallback to default ordering

        elif search_type == "text" and HAS_POSTGRES_SEARCH:
            try:
                from django.db import connection

                base_image_ids = list(images.values_list("id", flat=True))
                distance_threshold = 0.7  # A reasonable default

                if not base_image_ids:
                    images = Image.objects.none()
                else:
                    with connection.cursor() as cursor:
                        sql = """
                            SELECT id, LEAST(
                                COALESCE(%(query)s <<-> title, 1.0),
                                COALESCE(%(query)s <<-> description, 1.0)
                            ) as distance
                            FROM images_image
                            WHERE id = ANY(%(ids)s)
                            AND LEAST(
                                COALESCE(%(query)s <<-> title, 1.0),
                                COALESCE(%(query)s <<-> description, 1.0)
                            ) < %(threshold)s
                            ORDER BY distance ASC
                        """
                        params = {
                            "query": query,
                            "ids": base_image_ids,
                            "threshold": distance_threshold,
                        }
                        cursor.execute(sql, params)
                        result_ids = [row[0] for row in cursor.fetchall()]

                    if not result_ids:
                        images = Image.objects.none()
                    else:
                        preserved_order = Case(
                            *[
                                When(pk=pk, then=pos)
                                for pos, pk in enumerate(result_ids)
                            ]
                        )
                        images = Image.objects.filter(id__in=result_ids).order_by(
                            preserved_order
                        )
            except Exception:
                images = images.order_by("id")
        else:
            # If search is requested but not possible, just order by ID
            images = images.order_by("id")
    else:
        # No query, default ordering
        images = images.order_by("id")

    image_data = []
    for image in images:
        image_data.append(
            {
                "id": image.id,
                "title": image.title,
                "permalink": image.permalink,
                "description": image.description,
                "date_display": image.date_display,
                "scale": image.scale,
                "absolute_url": image.get_absolute_url(),
            }
        )

    context = {
        "title": "Label Image Scales",
        "images": images,
        "image_data_json": json.dumps(image_data),
        "site_title": "Georef Admin",
        "site_header": "Image Georeferencing Admin",
        "georeferenced_only": georeferenced_only,
        "search_query": query,
        "search_type": search_type,
    }

    return render(request, "admin/images/label_scales.html", context)


@require_http_methods(["POST"])
@staff_member_required
def update_image_scale(request):
    """
    API endpoint to update the scale of an image from the labeling interface.
    """
    image_id = request.POST.get("image_id")
    scale = request.POST.get("scale")

    image = get_object_or_404(Image, id=image_id)

    try:
        scale_val = int(scale)
        if 1 <= scale_val <= 5:
            image.scale = scale_val
            image.save(update_fields=["scale"])
            return JsonResponse(
                {"success": True, "message": f"Image scale marked as {scale}"}
            )
        else:
            return JsonResponse(
                {"success": False, "error": "Invalid scale value"}, status=400
            )
    except (ValueError, TypeError):
        return JsonResponse(
            {"success": False, "error": "Invalid scale value"}, status=400
        )
