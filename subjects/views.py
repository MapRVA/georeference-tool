import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import connection, models, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.functions import Lower
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from images.models import Image, SubjectMapping, TopRatedImageView

from .models import Subject, WikidataItem

# Try to import CLIP dependencies (for subject similarity search)
try:
    import clip
    import numpy as np
    import torch

    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False


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


def wikidata_lookup(request):
    """Look up a Wikidata item by ID and return subject info (creates if needed)"""
    wikidata_id = request.GET.get("id", "").strip().upper()

    if not wikidata_id or not wikidata_id.startswith("Q"):
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid Wikidata ID format. Must start with 'Q'.",
            },
            status=400,
        )

    try:
        # Get or create WikidataItem (this fetches from Wikidata API if new)
        wikidata_item, _ = WikidataItem.objects.get_or_create(wikidata_id=wikidata_id)

        # Get or create Subject
        subject, _ = Subject.objects.get_or_create(
            wikidata_item=wikidata_item,
            defaults={
                "title": wikidata_item.title,
                "description": wikidata_item.description
                or f"Subject from Wikidata: {wikidata_id}",
            },
        )

        return JsonResponse(
            {
                "success": True,
                "subject": {
                    "id": subject.id,
                    "title": subject.title,
                    "description": subject.description,
                    "wikidata_id": wikidata_id,
                },
            }
        )

    except ValidationError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Error looking up Wikidata item: {str(e)}"},
            status=500,
        )


def all_subjects_api(request):
    """API endpoint to get all subjects as JSON"""
    subjects = Subject.objects.all().values("id", "title")
    return JsonResponse(list(subjects), safe=False)


@require_http_methods(["POST"])
def bulk_add_subject_to_images(request):
    """Add a subject to multiple images at once (logged-in users only)"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "You must be logged in to edit subjects"},
            status=403,
        )

    try:
        data = json.loads(request.body)
        image_ids = data.get("image_ids", [])
        wikidata_id = data.get("wikidata_id", "").strip()

        if not image_ids:
            return JsonResponse(
                {"success": False, "error": "No images selected"},
                status=400,
            )

        if not wikidata_id or not wikidata_id.startswith("Q"):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid Wikidata ID format. Must start with 'Q'.",
                },
                status=400,
            )

        # Get or create WikidataItem
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

        # Add subject to each image
        added_count = 0
        already_exists_count = 0

        with transaction.atomic():
            for image_id in image_ids:
                try:
                    image = Image.objects.get(id=image_id)

                    if SubjectMapping.objects.filter(
                        image=image, subject=subject
                    ).exists():
                        already_exists_count += 1
                        continue

                    max_order = (
                        SubjectMapping.objects.filter(image=image).aggregate(
                            max_order=models.Max("order")
                        )["max_order"]
                        or 0
                    )

                    SubjectMapping.objects.create(
                        image=image,
                        subject=subject,
                        order=max_order + 1,
                    )
                    added_count += 1

                except Image.DoesNotExist:
                    continue

        return JsonResponse(
            {
                "success": True,
                "added_count": added_count,
                "already_exists_count": already_exists_count,
                "subject": {
                    "id": subject.id,
                    "title": subject.title,
                    "description": subject.description,
                },
            },
            status=200,
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON in request body"},
            status=400,
        )
    except Exception as e:
        return JsonResponse(
            {"success": False, "error": str(e)},
            status=500,
        )


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

        # Render the subject card partial for live insertion
        html = render_to_string(
            "subjects/partials/subject_card.html",
            {"subject_relation": subject_mapping, "request": request},
            request=request,
        )

        return JsonResponse(
            {
                "success": True,
                "message": f"Subject '{subject.title}' added to image",
                "html": html,
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
    return render(request, "subjects/browse_subjects.html", context)


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
    return render(request, "subjects/subject_detail.html", context)


@ratelimit(key="ip", rate="1000/h", method=["GET", "POST"])  # 16/min average
@ratelimit(key="ip", rate="100/5m", method=["GET", "POST"])  # 20/min burst
def find_similar_images_to_subject(request, subject_slug):
    """
    Find and display images with embeddings most similar to the centroid
    of all images associated with a subject.

    Supports filtering via query parameters from filter_cards.html:
    - georeference_status: comma-separated values (georeferenced, pending, will_not_georef)
    - start_year, end_year: year range filtering
    - with_subjects: comma-separated subject IDs (images must have ALL)
    - without_subjects: comma-separated subject IDs (images must not have ANY)
    - no_subjects: if 'true', only images with no subjects
    """
    if not CLIP_AVAILABLE:
        messages.error(
            request,
            "Similarity search is not available. CLIP dependencies not installed.",
        )
        return redirect("subjects:subject_detail", subject_slug=subject_slug)

    # Get the target subject
    subject = get_object_or_404(Subject, slug=subject_slug)

    # Get all images for this subject that have embeddings
    subject_images = Image.objects.filter(
        subject_mappings__subject=subject,
        embedding__isnull=False,
        collection__public=True,
        collection__source__public=True,
        duplicate_of__isnull=True,
    ).distinct()

    if not subject_images.exists():
        messages.error(
            request,
            "This subject has no images with embeddings, so similar images cannot be found.",
        )
        return redirect("subjects:subject_detail", subject_slug=subject_slug)

    # Get filter parameters from URL (matching filter_cards.html)
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

    # Pagination parameters - use SQL-level pagination to avoid memory issues
    per_page = 24
    try:
        page_number = int(request.GET.get("page", 1))
        if page_number < 1:
            page_number = 1
    except (ValueError, TypeError):
        page_number = 1
    offset = (page_number - 1) * per_page

    try:
        # Calculate the centroid of all subject image embeddings
        subject_embeddings = []
        for img in subject_images:
            if img.embedding:
                subject_embeddings.append(np.array(img.embedding))

        if not subject_embeddings:
            messages.error(
                request,
                "Unable to calculate centroid - no valid embeddings found.",
            )
            return redirect("subjects:subject_detail", subject_slug=subject_slug)

        # Calculate centroid as the mean of all embeddings
        centroid_embedding = np.mean(subject_embeddings, axis=0)

        # Normalize the centroid (important for cosine similarity)
        centroid_embedding = centroid_embedding / np.linalg.norm(centroid_embedding)

        # Get IDs of subject images to exclude from results
        subject_image_ids = list(subject_images.values_list("id", flat=True))

        with connection.cursor() as cursor:
            # Convert centroid embedding to PostgreSQL array format
            embedding_str = "[" + ",".join(map(str, centroid_embedding.tolist())) + "]"

            # Build WHERE conditions
            where_conditions = ["embedding IS NOT NULL", "id != ALL(%s)"]
            where_params = [subject_image_ids]

            # Georeference status filtering (matching filter_cards.html behavior)
            if georeference_status:
                status_conditions = []
                if "georeferenced" in georeference_status:
                    status_conditions.append(
                        "(EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id) "
                        "OR (aerial = true AND EXISTS (SELECT 1 FROM images_aerialgeoreference ag WHERE ag.image_id = images_image.id)))"
                    )
                if "pending" in georeference_status:
                    status_conditions.append(
                        "((NOT EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id) "
                        "AND aerial = false AND will_not_georef = false) "
                        "OR (NOT EXISTS (SELECT 1 FROM images_aerialgeoreference ag WHERE ag.image_id = images_image.id) "
                        "AND aerial = true AND will_not_georef = false))"
                    )
                if "will_not_georef" in georeference_status:
                    status_conditions.append("will_not_georef = true")

                if status_conditions:
                    where_conditions.append(f"({' OR '.join(status_conditions)})")

            # Year range conditions
            if start_year:
                try:
                    start_year_int = int(start_year)
                    where_conditions.append(
                        "(fuzzy_start_decdate >= %s OR start_decdate >= %s)"
                    )
                    where_params.extend([start_year_int, start_year_int])
                except ValueError:
                    pass
            if end_year:
                try:
                    end_year_int = int(end_year)
                    where_conditions.append(
                        "(fuzzy_end_decdate <= %s OR end_decdate <= %s)"
                    )
                    where_params.extend([end_year_int, end_year_int])
                except ValueError:
                    pass

            # Subject filtering
            if no_subjects:
                where_conditions.append(
                    "NOT EXISTS (SELECT 1 FROM images_subjectmapping sm WHERE sm.image_id = images_image.id)"
                )
            elif with_subjects:
                # Images must have ALL specified subjects
                for subject_id in with_subjects:
                    if subject_id:
                        where_conditions.append(
                            "EXISTS (SELECT 1 FROM images_subjectmapping sm WHERE sm.image_id = images_image.id AND sm.subject_id = %s)"
                        )
                        where_params.append(subject_id)
            elif without_subjects:
                # Images must not have ANY of the specified subjects
                valid_ids = [sid for sid in without_subjects if sid]
                if valid_ids:
                    placeholders = ", ".join(["%s"] * len(valid_ids))
                    where_conditions.append(
                        f"NOT EXISTS (SELECT 1 FROM images_subjectmapping sm WHERE sm.image_id = images_image.id AND sm.subject_id IN ({placeholders}))"
                    )
                    where_params.extend(valid_ids)

            where_clause = " AND ".join(where_conditions)

            # Get total count for pagination
            count_sql = f"""
                SELECT COUNT(id)
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

            # SQL-level pagination - only fetch the IDs we need for this page
            query_sql = f"""
                SELECT
                    id,
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
                ORDER BY distance, id ASC
                LIMIT %s OFFSET %s
            """
            cursor.execute(
                query_sql,
                [embedding_str] + where_params + [per_page, offset],
            )
            page_results = cursor.fetchall()

        # Get the IDs for this page only
        current_page_ids = [row[0] for row in page_results]

        # Get the full Image objects for the current page
        images_on_page = Image.objects.filter(id__in=current_page_ids).select_related(
            "collection__source"
        )

        # Create a dictionary to map IDs to image objects for correct ordering
        images_by_id = {img.id: img for img in images_on_page}

        # Re-order the fetched image objects based on the result order
        ordered_images_on_page = [
            images_by_id[img_id]
            for img_id in current_page_ids
            if img_id in images_by_id
        ]

        # Create a simple page object for template compatibility
        total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1

        class SimplePaginator:
            def __init__(self, num_pages, count, per_page):
                self.num_pages = num_pages
                self.count = count
                self.per_page = per_page

            @property
            def page_range(self):
                return range(1, self.num_pages + 1)

        class SimplePage:
            def __init__(self, object_list, number, total_pages, total_count, per_page):
                self.object_list = object_list
                self.number = number
                self._per_page = per_page
                self._total_count = total_count
                self.paginator = SimplePaginator(total_pages, total_count, per_page)

            def __iter__(self):
                return iter(self.object_list)

            def __len__(self):
                return len(self.object_list)

            def has_previous(self):
                return self.number > 1

            def has_next(self):
                return self.number < self.paginator.num_pages

            def previous_page_number(self):
                return self.number - 1

            def next_page_number(self):
                return self.number + 1

            @property
            def start_index(self):
                if self._total_count == 0:
                    return 0
                return (self.number - 1) * self._per_page + 1

            @property
            def end_index(self):
                if self._total_count == 0:
                    return 0
                return min(self.number * self._per_page, self._total_count)

        page_obj = SimplePage(
            ordered_images_on_page, page_number, total_pages, total_count, per_page
        )

        # Get total number of images for this subject
        total_subject_images = (
            Image.objects.filter(
                subject_mappings__subject=subject,
                collection__public=True,
                collection__source__public=True,
                duplicate_of__isnull=True,
            )
            .distinct()
            .count()
        )

        context = {
            "subject": subject,
            "subject_image_count": subject_images.count(),
            "total_subject_images": total_subject_images,
            "page_obj": page_obj,
            "total_similar_count": total_count,
        }

        return render(request, "subjects/subject_similar_images.html", context)

    except Exception as e:
        messages.error(
            request, f"An error occurred while finding similar images: {str(e)}"
        )
        return redirect("subjects:subject_detail", subject_slug=subject_slug)
