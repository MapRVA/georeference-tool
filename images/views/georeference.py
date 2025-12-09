import json

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import Point, GEOSGeometry
from django.db import IntegrityError, models, transaction
from django.db.models import Case, When
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import (
    AerialGeoreference,
    Album,
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    Source,
    Subject,
)


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
            # Also allow aerials if user is an admin
            query_params = {
                "id": int(image_id),
                "will_not_georef": False,
                "duplicate_of__isnull": True,
                "collection__public": True,
                "collection__source__public": True,
            }

            # Only allow aerials for admin users
            if not request.user.is_staff:
                query_params["aerial"] = False

            current_image = Image.objects.get(**query_params)

            # If image is aerial but user is not admin, raise 403 Forbidden
            if current_image.aerial and not request.user.is_staff:
                raise PermissionDenied("Only admins can georeference aerial images")
        except (Image.DoesNotExist, ValueError):
            # If specific image not found or invalid, fall back to random selection
            pass

    # Start with all ungeoreferenced images from public sources/collections
    # Exclude duplicate images from being suggested
    images = Image.objects.filter(
        georeferences__isnull=True,
        will_not_georef=False,
        aerial=False,
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
            if not album.public and (
                not request.user.is_authenticated or album.owner != request.user
            ):
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
        "next_image": current_image.get_next_image() if current_image else None,
        "previous_image": current_image.get_previous_image() if current_image else None,
    }

    # Remove duplicate message - template already shows appropriate message when no image available

    return render(request, "images/georeference_interface.html", context)


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


@login_required
def aerial_georeference_interface(request, image_id):
    """Display the aerial georeference interface for a specific image"""
    try:
        image = get_object_or_404(
            Image,
            id=image_id,
            aerial=True,
            will_not_georef=False,
            duplicate_of__isnull=True,
            collection__public=True,
            collection__source__public=True,
        )
    except Http404:
        return render(
            request,
            "images/aerial_georeference_interface.html",
            {"image": None},
            status=404,
        )

    # Get OSM authentication info
    osm_authenticated = (
        hasattr(request.user, "osm_profile") and request.user.osm_profile is not None
    )
    osm_username = request.user.osm_profile.display_name if osm_authenticated else None

    # Get the existing aerial georeference if it exists
    aerial_georeference = image.get_aerial_georeference()

    context = {
        "image": image,
        "aerial_georeference": aerial_georeference,
        "osm_authenticated": osm_authenticated,
        "osm_username": osm_username,
        "user": request.user,
    }

    return render(request, "images/from_above_georeference_interface.html", context)


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def aerial_georeference_image(request, image_id):
    """API endpoint to submit an aerial georeference with polygon"""
    try:
        data = json.loads(request.body)
        image = get_object_or_404(Image, id=image_id, aerial=True)

        # Check if image is a duplicate
        if image.duplicate_of:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Cannot georeference duplicate images. This image is marked as a duplicate of another image.",
                },
                status=400,
            )

        # Validate required fields
        required_fields = ["polygon", "confidence"]
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

        # Validate polygon geometry
        if not isinstance(data["polygon"], dict) or data["polygon"].get("type") not in [
            "Polygon",
            "MultiPolygon",
        ]:
            return JsonResponse(
                {"success": False, "error": "Invalid polygon geometry"},
                status=400,
            )

        try:
            # Convert GeoJSON to WKT format for storage
            polygon_geojson = json.dumps(data["polygon"])
            polygon = GEOSGeometry(polygon_geojson)

            # If a MultiPolygon was submitted, validate it contains only one polygon
            if polygon.geom_type == "MultiPolygon":
                if len(polygon) == 0:
                    return JsonResponse(
                        {"success": False, "error": "MultiPolygon is empty"},
                        status=400,
                    )
                elif len(polygon) > 1:
                    return JsonResponse(
                        {
                            "success": False,
                            "error": f"MultiPolygon contains {len(polygon)} polygons. Please draw only one polygon.",
                        },
                        status=400,
                    )
                else:
                    # Single polygon in a MultiPolygon wrapper, extract it
                    polygon = polygon[0]
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": f"Invalid polygon format: {str(e)}"},
                status=400,
            )

        # Handle aerial georeference creation/update
        aerial_georeference = None
        try:
            with transaction.atomic():
                aerial_georeference = AerialGeoreference.objects.create(
                    image=image,
                    polygon=polygon,
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
                    aerial_georeference = AerialGeoreference.objects.filter(
                        image=image, georeferenced_by=request.user
                    ).first()
                    if aerial_georeference:
                        aerial_georeference.polygon = polygon
                        aerial_georeference.confidence = data["confidence"]
                        aerial_georeference.confidence_notes = data.get("notes", "")
                        aerial_georeference.save()
                    else:
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Unable to update existing georeference",
                            },
                            status=500,
                        )
            else:
                return JsonResponse(
                    {"success": False, "error": "Unable to create georeference"},
                    status=500,
                )

        return JsonResponse(
            {
                "success": True,
                "georeference_id": aerial_georeference.id,
                "message": "Polygonal georeference successfully created",
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON format"}, status=400
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
