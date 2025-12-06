import json
from pathlib import Path

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.gis.geos import Point, GEOSGeometry
from django.core.paginator import Page, Paginator
from django.db import IntegrityError, models, transaction
from django.db.models import Avg, Case, Count, Func, IntegerField, Q, Value, When
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

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
    LayerCollection,
    TopRatedImageView,
    Source,
    Subject,
    SubjectMapping,
    WikidataItem,
)
from ..utils import render_markdown_safe


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
