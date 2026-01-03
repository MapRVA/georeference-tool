import json
from pathlib import Path

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.gis.geos import Point, GEOSGeometry
from django.core.paginator import Page, Paginator
from django.db import connection, IntegrityError, models, transaction
from django.db.models import Avg, Case, Count, Func, IntegerField, Q, Value, When
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django.core.exceptions import ValidationError

from ..models import (
    AerialGeoreference,
    Album,
    Collection,
    Comment,
    Georeference,
    GeoreferenceValidation,
    Image,
    ImageRating,
    ImageSkip,
    TopRatedImageView,
    Source,
    Subject,
    SubjectMapping,
    WikidataItem,
)
from ..utils import render_markdown_safe

# Try to import CLIP dependencies (for subject similarity search)
try:
    import clip
    import torch
    import numpy as np

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


def find_similar_images_to_subject(request, subject_slug):
    """
    Find and display images with embeddings most similar to the centroid
    of all images associated with a subject.
    Supports filtering by georeferenced status via query parameter.
    """
    if not CLIP_AVAILABLE:
        messages.error(
            request,
            "Similarity search is not available. CLIP dependencies not installed.",
        )
        return redirect("images:subject_detail", subject_slug=subject_slug)

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
        return redirect("images:subject_detail", subject_slug=subject_slug)

    # Get georeferenced filter from query parameter
    georeferenced_status = request.GET.get(
        "georeferenced", "all"
    )  # 'all', 'yes', or 'none'

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
            return redirect("images:subject_detail", subject_slug=subject_slug)

        # Calculate centroid as the mean of all embeddings
        centroid_embedding = np.mean(subject_embeddings, axis=0)

        # Normalize the centroid (important for cosine similarity)
        centroid_embedding = centroid_embedding / np.linalg.norm(centroid_embedding)

        # Get IDs of subject images to exclude from results
        subject_image_ids = list(subject_images.values_list("id", flat=True))

        with connection.cursor() as cursor:
            # Convert centroid embedding to PostgreSQL array format
            embedding_str = "[" + ",".join(map(str, centroid_embedding.tolist())) + "]"

            # Build WHERE conditions based on georeferenced filter
            georeference_condition = ""
            if georeferenced_status == "yes":
                georeference_condition = "AND EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"
            elif georeferenced_status == "none":
                georeference_condition = "AND NOT EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"

            # Raw SQL query for cosine similarity to get all similar images
            # Exclude images that are already part of this subject
            sql = f"""
                SELECT
                    id,
                    (embedding::vector <=> %s::vector) as distance
                FROM images_image
                WHERE embedding IS NOT NULL
                AND id != ALL(%s)
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
            cursor.execute(sql, [embedding_str, subject_image_ids])
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
            "total_similar_count": paginator.count,
            "georeferenced_status": georeferenced_status,
        }

        return render(request, "images/subject_similar_images.html", context)

    except Exception as e:
        messages.error(
            request, f"An error occurred while finding similar images: {str(e)}"
        )
        return redirect("images:subject_detail", subject_slug=subject_slug)
