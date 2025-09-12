import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    ImageSkip,
    Source,
)


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
            collection__source=source, collection__public=True
        ).count()
        source.georeferenced_images = (
            Image.objects.filter(
                collection__source=source,
                collection__public=True,
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
        collection.total_images = collection.images.count()
        collection.georeferenced_images = (
            collection.images.filter(georeferences__isnull=False).distinct().count()
        )
        collection.pending_images = (
            collection.total_images - collection.georeferenced_images
        )

    # Overall source statistics (only from public collections)
    total_images = Image.objects.filter(
        collection__source=source, collection__public=True
    ).count()
    georeferenced_images = (
        Image.objects.filter(
            collection__source=source,
            collection__public=True,
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
        "pending_images": total_images - georeferenced_images,
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

    images = collection.images.all()
    total_images = images.count()
    georeferenced_images = images.filter(georeferences__isnull=False).distinct().count()

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
        "pending_images": total_images - georeferenced_images,
        "completion_percentage": (georeferenced_images / total_images * 100)
        if total_images > 0
        else 0,
    }
    return render(request, "images/collection_detail.html", context)


def georeference_interface(request):
    """Main georeferencing interface - can be filtered by source/collection or show specific image"""
    source_slug = request.GET.get("source")
    collection_slug = request.GET.get("collection")
    difficulty = request.GET.get("difficulty")
    image_id = request.GET.get("image")

    # If specific image ID is requested, try to load it
    current_image = None
    if image_id:
        try:
            # For specific image requests, allow both georeferenced and ungeoreferenced images
            # This enables corrections for already georeferenced images
            current_image = Image.objects.get(
                id=int(image_id),
                will_not_georef=False,
                collection__public=True,
                collection__source__public=True,
            )
        except (Image.DoesNotExist, ValueError):
            # If specific image not found or invalid, fall back to random selection
            pass

    # Start with all ungeoreferenced images from public sources/collections
    images = Image.objects.filter(
        georeferences__isnull=True,
        will_not_georef=False,
        collection__public=True,
        collection__source__public=True,
    )

    # Exclude images this user has already skipped (only if user is authenticated)
    if request.user.is_authenticated:
        images = images.exclude(skips__user=request.user)

    images = images.select_related("collection__source")

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

    # Filter by difficulty if specified
    if difficulty in ["easy", "medium", "hard"]:
        images = images.filter(difficulty=difficulty)

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
        "difficulty_filter": difficulty,
        "remaining_count": images.count(),
    }

    if not current_image:
        messages.info(
            request,
            "No more images available for georeferencing with your current filters.",
        )

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

    context = {
        "image": image,
        "has_georeference": image.georeferences.exists(),
        "georeference": image.get_georeference(),
        "validations": image.get_georeference().validations.all()
        if image.get_georeference()
        else [],
    }

    return render(request, "images/image_detail.html", context)


@require_http_methods(["POST"])
@csrf_exempt
def georeference_image(request, image_id):
    """API endpoint to georeference an image"""
    try:
        data = json.loads(request.body)
        image = get_object_or_404(Image, id=image_id)

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

        # Validate business rules
        # Rule 1: High confidence requires a direction
        if data["confidence"] == "high" and not data.get("direction"):
            return JsonResponse(
                {
                    "success": False,
                    "error": "High confidence requires specifying a direction",
                },
                status=400,
            )

        # Rule 2: Low confidence requires notes
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
                    latitude=float(data["latitude"]),
                    longitude=float(data["longitude"]),
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
                        georeference.latitude = float(data["latitude"])
                        georeference.longitude = float(data["longitude"])
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
def skip_image(request, image_id):
    """API endpoint to skip an image"""
    try:
        data = json.loads(request.body)
        image = get_object_or_404(Image, id=image_id)

        # Only track skips for authenticated users
        if request.user.is_authenticated:
            with transaction.atomic():
                skip, created = ImageSkip.objects.get_or_create(
                    image=image,
                    user=request.user,
                    defaults={"reason": data.get("reason", "")},
                )

            if not created:
                return JsonResponse(
                    {"success": False, "error": "You have already skipped this image"}
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

    image.will_not_georef = True
    image.save(update_fields=["will_not_georef"])
    return JsonResponse(
        {"success": True, "message": 'Image marked as "will not georeference"'}
    )


def get_random_image(request):
    """Get a random image for georeferencing"""
    # Get images that haven't been georeferenced and aren't marked as will_not_georef
    available_images = Image.objects.filter(
        georeferences__isnull=True,
        will_not_georef=False,
        collection__public=True,
        collection__source__public=True,
    )

    # Exclude images this user has already skipped (only if user is authenticated)
    if request.user.is_authenticated:
        available_images = available_images.exclude(skips__user=request.user)

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


def geojson_endpoint(request):
    """Return GeoJSON FeatureCollection of georeferenced images"""
    from django.urls import reverse

    # Start with all georeferenced images from public collections/sources
    images = (
        Image.objects.select_related("collection__source")
        .prefetch_related("georeferences")
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

    if image_id:
        images = images.filter(id=image_id)
    if collection_id:
        images = images.filter(collection_id=collection_id)
    if source_id:
        images = images.filter(collection__source_id=source_id)

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
            "date": str(image.original_date) if image.original_date else None,
        }

        # Only include direction if it's not None
        if georeference.direction is not None:
            properties["direction"] = georeference.direction

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [georeference.longitude, georeference.latitude],
            },
            "properties": properties,
        }
        features.append(feature)

    # Build final GeoJSON
    geojson = {"type": "FeatureCollection", "features": features}

    return JsonResponse(geojson)
