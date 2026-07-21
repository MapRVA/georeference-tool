import json
import traceback

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Avg, Case, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import (
    CollectionStats,
    Comment,
    Image,
    ImageRating,
    ImageSkip,
)
from .search import _get_text_embedding

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
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_http_methods(["POST", "DELETE"])
@csrf_exempt
def submit_rating(request, image_id):
    """API endpoint to submit, update, or delete a rating for an image"""
    # Check if user is authenticated
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )

    try:
        image = get_object_or_404(Image, id=image_id)

        # Handle DELETE request (clear rating)
        if request.method == "DELETE":
            with transaction.atomic():
                deleted_count, _ = ImageRating.objects.filter(
                    image=image, user=request.user
                ).delete()

                if deleted_count == 0:
                    return JsonResponse(
                        {"success": False, "error": "No rating found to delete"},
                        status=404,
                    )

            # Get updated average rating and count after deletion
            image_ratings = image.ratings.all()
            avg_rating = image_ratings.aggregate(Avg("rating"))["rating__avg"]
            rating_count = image_ratings.count()

            return JsonResponse(
                {
                    "success": True,
                    "message": "Rating cleared successfully",
                    "user_rating": None,
                    "avg_rating": float(avg_rating) if avg_rating else None,
                    "rating_count": rating_count,
                }
            )

        # Handle POST request (submit/update rating)
        data = json.loads(request.body)

        rating = data.get("rating")
        if rating is None:
            return JsonResponse(
                {"success": False, "error": "Missing 'rating' field"}, status=400
            )

        # Validate rating is an integer between 1 and 10
        try:
            rating = int(rating)
        except (ValueError, TypeError):
            return JsonResponse(
                {"success": False, "error": "Rating must be an integer"}, status=400
            )

        if not (1 <= rating <= 10):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Rating must be between 1 and 10",
                },
                status=400,
            )

        # Use update_or_create to handle both new ratings and updates
        with transaction.atomic():
            image_rating, created = ImageRating.objects.update_or_create(
                image=image,
                user=request.user,
                defaults={"rating": rating},
            )

        # Get updated average rating and count
        image_ratings = image.ratings.all()
        avg_rating = image_ratings.aggregate(Avg("rating"))["rating__avg"]
        rating_count = image_ratings.count()

        return JsonResponse(
            {
                "success": True,
                "message": "Rating submitted successfully",
                "rating_id": image_rating.id,
                "user_rating": rating,
                "avg_rating": float(avg_rating) if avg_rating else None,
                "rating_count": rating_count,
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON in request body"}, status=400
        )
    except Image.DoesNotExist:
        return JsonResponse({"success": False, "error": "Image not found"}, status=404)
    except Exception as e:
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


@require_http_methods(["POST"])
def mark_aerial(request, image_id):
    """Toggle the aerial flag for an image (admin only)"""
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
    aerial = request.POST.get("aerial", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    image.aerial = aerial
    image.save(update_fields=["aerial"])
    message = "Image marked as aerial" if aerial else "Removed aerial marking"
    return JsonResponse({"success": True, "message": message})


def _bulk_set_image_flag(request, field):
    """
    Set a boolean flag to True on many images at once (admin only).

    Shared implementation for the bulk "mark as from above" / "mark as will not
    georeference" actions. A queryset UPDATE bypasses the post_save signal that
    keeps CollectionStats in sync, so we refresh the affected collections here.
    """
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )
    if not request.user.is_staff:
        return JsonResponse(
            {"success": False, "error": "Admin permissions required"}, status=403
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON in request body"}, status=400
        )

    try:
        image_ids = [int(image_id) for image_id in data.get("image_ids", [])]
    except (AttributeError, TypeError, ValueError):
        return JsonResponse(
            {"success": False, "error": "Invalid image IDs"}, status=400
        )

    if not image_ids:
        return JsonResponse(
            {"success": False, "error": "No images selected"}, status=400
        )

    # Only images that don't already have the flag set will actually change.
    # Filtering to those makes .update() return the true number changed
    # (total selected minus those previously tagged).
    images = Image.objects.filter(id__in=image_ids, **{field: False})
    collection_ids = list(images.values_list("collection_id", flat=True).distinct())
    updated_count = images.update(**{field: True})

    # The queryset UPDATE above skips the post_save signal, so refresh the
    # denormalized stats for the affected collections directly.
    CollectionStats.refresh_for(collection_ids)

    return JsonResponse({"success": True, "updated_count": updated_count})


@require_http_methods(["POST"])
def bulk_mark_aerial(request):
    """Mark multiple images as aerial ("from above") at once (admin only)."""
    return _bulk_set_image_flag(request, "aerial")


@require_http_methods(["POST"])
def bulk_mark_will_not_georef(request):
    """Mark multiple images as "will not georeference" at once (admin only)."""
    return _bulk_set_image_flag(request, "will_not_georef")


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
        if search_type == "semantic":
            try:
                query_embedding = _get_text_embedding(query)
                embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
                base_image_ids = list(images.values_list("id", flat=True))

                if not base_image_ids:
                    images = Image.objects.none()
                else:
                    with connection.cursor() as cursor:
                        # Find images with embeddings and order by similarity
                        sql = """
                            SELECT id, (embedding::vector(768) <=> %s::vector(768)) as distance
                            FROM images_image
                            WHERE id = ANY(%s) AND embedding IS NOT NULL
                            ORDER BY embedding::vector(768) <=> %s::vector(768)
                        """
                        cursor.execute(
                            sql, [embedding_str, base_image_ids, embedding_str]
                        )
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
                "permalink": image.display_permalink,
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
