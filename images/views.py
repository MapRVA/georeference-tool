import json
from pathlib import Path

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, models, transaction
from django.db.models import Case, Func, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    ImageSkip,
    LayerCollection,
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
            collection__source=source, collection__public=True, duplicate_of__isnull=True
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
        collection.total_images = collection.images.filter(duplicate_of__isnull=True).count()
        collection.georeferenced_images = (
            collection.images.filter(duplicate_of__isnull=True, georeferences__isnull=False).distinct().count()
        )
        collection.pending_images = (
            collection.total_images - collection.georeferenced_images
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

    # Sort images: georeferenced images second-to-last, "will not reference" images at the end
    # Exclude duplicate images from the collection view
    images = collection.images.filter(duplicate_of__isnull=True).annotate(
        has_georeference=Case(
            When(georeferences__isnull=False, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by("will_not_georef", "has_georeference", "id")
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
    context = {
        "clip_available": CLIP_AVAILABLE,
    }
    return render(request, "images/search.html", context)


def geojson_endpoint(request):
    """Return GeoJSON FeatureCollection of georeferenced images"""

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

    # Check for local model
    local_model_path = Path("./models/ViT-L-14-336px.pt").absolute()
    print(local_model_path)
    model_name = "ViT-L/14@336px"

    if local_model_path.exists():
        _clip_model, _clip_preprocess = clip.load(
            model_name, device=_clip_device, download_root=local_model_path.parent
        )
    else:
        _clip_model, _clip_preprocess = clip.load(model_name, device=_clip_device)

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

    # Get search parameters
    limit = min(int(request.GET.get("limit", 20)), 100)  # Max 100 results
    include_no_embedding = (
        request.GET.get("include_no_embedding", "false").lower() == "true"
    )
    georeferenced_only = (
        request.GET.get("georeferenced_only", "false").lower() == "true"
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

        # Base queryset - only public images
        images = Image.objects.filter(
            collection__public=True, collection__source__public=True
        ).select_related("collection__source")

        # Filter to images with embeddings (unless explicitly including those without)
        if not include_no_embedding:
            images = images.filter(embedding__isnull=False)

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

            # Combine all WHERE conditions
            where_clause = " AND ".join(where_conditions)

            # Raw SQL query for cosine similarity
            # Cast the array to vector type for pgvector operations
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
                    WHERE c.public = true AND s.public = true
                )
                ORDER BY embedding::vector <=> %s::vector
                LIMIT %s
            """

            # Build the final parameter list in the correct order:
            # 1. First embedding for distance calculation
            # 2. WHERE clause parameters (years)
            # 3. Second embedding for ORDER BY
            # 4. LIMIT parameter
            query_params = [embedding_str] + where_params + [embedding_str, limit]

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
                }

                # Add georeference data if available
                if image.is_georeferenced:
                    georeference = image.get_georeference()
                    if georeference:
                        result["georeference"] = {
                            "latitude": georeference.latitude,
                            "longitude": georeference.longitude,
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
                "count": len(search_results),
                "limit": limit,
            }
        )

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Search failed: {str(e)}"}, status=500
        )


class WordSimilarity(Func):
    function = "word_similarity"
    arity = 2


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

    if not query:
        return JsonResponse(
            {
                "success": False,
                "error": "Query parameter 'q' (GET) or 'query' (POST) is required",
            },
            status=400,
        )

    # Get search parameters
    limit = min(int(request.GET.get("limit", 20)), 100)
    georeferenced_only = (
        request.GET.get("georeferenced_only", "false").lower() == "true"
    )
    # Distance is 1 - similarity. A lower distance is a better match.
    distance_threshold = float(request.GET.get("threshold", 0.7))

    # Year filtering parameters
    start_year = request.GET.get("start_year")
    end_year = request.GET.get("end_year")

    # --- Start of Query Logic ---
    try:
        # 1. Use the ORM for initial filtering (easier for optional filters)
        images = Image.objects.filter(
            collection__public=True, collection__source__public=True
        )

        if georeferenced_only:
            images = images.filter(georeferences__isnull=False).distinct()

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

        filtered_ids = list(images.values_list("id", flat=True))

        if not filtered_ids:
            return JsonResponse(
                {"success": True, "query": query, "results": [], "count": 0}
            )

        # 2. Use Raw SQL for the complex trigram query for performance and control
        from django.db import connection

        with connection.cursor() as cursor:
            # Note: We use the word distance operator `<<->` which is ideal for this use case.
            # It finds the distance between the query and the most similar word in the target text.
            # A distance of 0 is a perfect match, 1 is a total mismatch.
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
            """
            params = {
                "query": query,
                "ids": filtered_ids,
                "threshold": distance_threshold,
                "limit": limit,
            }
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        # 3. Format the results
        search_results = []
        for row in rows:
            # Unpack row data
            image_id, title, permalink, original_date, edtf_date, distance = row

            # Get the full image object for properties that are not simple fields
            image = Image.objects.get(id=image_id)

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
            }
            search_results.append(result)

        return JsonResponse(
            {
                "success": True,
                "query": query,
                "results": search_results,
                "count": len(search_results),
                "limit": limit,
                "search_type": "word_distance",
            }
        )

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Text search failed: {str(e)}"}, status=500
        )
