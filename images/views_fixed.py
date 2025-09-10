from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import transaction, IntegrityError
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
import json

from .models import (
    Source,
    Collection,
    Image,
    Georeference,
    GeoreferenceValidation,
    ImageSkip,
)


@require_http_methods(["POST"])
@csrf_exempt
def georeference_image(request, image_id):
    """API endpoint to georeference an image - allows multiple submissions per user"""
    try:
        data = json.loads(request.body)
        image = get_object_or_404(Image, id=image_id)

        # For anonymous users, check if they can still georeference
        # For authenticated users, allow multiple submissions (corrections)
        if not request.user.is_authenticated:
            # Anonymous users can only georeference if no georeferences exist yet
            if image.georeferences.exists():
                return JsonResponse(
                    {"success": False, "error": "This image has already been georeferenced. Please login to submit a correction."},
                    status=400,
                )

        # Validate required fields
        required_fields = ["latitude", "longitude"]
        for field in required_fields:
            if field not in data:
                return JsonResponse(
                    {"success": False, "error": f"Missing required field: {field}"},
                    status=400,
                )

        # Create a new georeference (no unique constraint, allows multiple per user per image)
        with transaction.atomic():
            georeference = Georeference.objects.create(
                image=image,
                latitude=float(data["latitude"]),
                longitude=float(data["longitude"]),
                direction=int(data["direction"]) if data.get("direction") else None,
                georeferenced_by=request.user if request.user.is_authenticated else None,
                confidence_notes=data.get("notes", ""),
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
