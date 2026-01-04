import json
import logging
import re
import threading
from io import BytesIO
from pathlib import Path
from contextlib import ExitStack

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import DatabaseError, connection
from django.db.models import Func
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from PIL import Image as PILImage
from psycopg import sql

from ..models import Image

logger = logging.getLogger(__name__)

# Query security settings
MAX_TEXT_QUERY_LENGTH = 500  # Reasonable limit for CLIP text queries

# Image security settings
MAX_IMAGE_PIXELS = 89_000_000  # ~89 megapixels
PILImage.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
MAX_DIMENSION = 10000  # Max width or height
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


# Global variables for CLIP model (loaded on first use)
_clip_model = None
_clip_preprocess = None
_clip_device = None
_clip_model_lock = threading.Lock()


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


def search_page(request):
    """Display the semantic search interface"""
    context = {
        "clip_available": CLIP_AVAILABLE,
    }
    return render(request, "images/search.html", context)


def _load_clip_model():
    """Load CLIP model on first use (cached per-worker, thread-safe)"""
    global _clip_model, _clip_preprocess, _clip_device

    # Fast path: model already loaded (no lock needed)
    if _clip_model is not None:
        return _clip_model, _clip_preprocess, _clip_device

    # Slow path: acquire lock to prevent concurrent loading
    with _clip_model_lock:
        # Double-check after acquiring lock (another thread may have loaded it)
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


def _sanitize_image(uploaded_file, max_pixels=MAX_IMAGE_PIXELS):
    """
    Re-encode image, an attempt to sidestep malicious content.

    Args:
        uploaded_file: Django UploadedFile object
        max_pixels: Maximum total pixel count allowed

    Returns:
        BytesIO: Image data re-encoded as PNG
    """
    try:
        # Open image
        img = PILImage.open(uploaded_file)

        # Validate format (must be done before .load())
        if img.format not in ALLOWED_FORMATS:
            raise ValueError(
                f"Image format '{img.format}' not supported. "
                f"Allowed formats: {', '.join(sorted(ALLOWED_FORMATS))}"
            )

        # Force full decompression to trigger any issues
        img.load()

        # Check individual dimensions
        if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
            raise ValueError(
                f"Image dimensions ({img.width}x{img.height}) exceed "
                f"maximum {MAX_DIMENSION}px per side"
            )

        # Check total pixel count (decompression bomb protection)
        total_pixels = img.width * img.height
        if total_pixels > max_pixels:
            raise ValueError(
                f"Image has too many pixels ({total_pixels:,}). Maximum: {max_pixels:,}"
            )

        # Convert to RGB if necessary (normalizes color modes)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Re-encode to a clean buffer (strips metadata and malicious content)
        output = BytesIO()
        img.save(output, format="PNG")  # Always save as PNG for consistency
        output.seek(0)

        return output

    except ValueError:
        # Re-raise our custom validation errors (safe messages)
        raise
    except PILImage.DecompressionBombError:
        # Explicit handling of decompression bombs
        logger.warning("Decompression bomb detected in uploaded image")
        raise ValueError("Image rejected: decompression bomb detected")
    except Exception as e:
        # Catch any Pillow parsing/processing errors
        # Log technical details but return generic message
        logger.warning(f"Image sanitization failed: {type(e).__name__}: {e}")
        raise ValueError("Invalid or corrupted image file")


def _get_image_embedding(image):
    """Generate embedding for an image using CLIP"""
    model, preprocess, device = _load_clip_model()

    with ExitStack() as stack:
        if isinstance(image, (str, Path)):
            # If image is a file path or file object, open it
            pil_image = stack.enter_context(PILImage.open(image))
            pil_image = pil_image.convert("RGB")
        elif hasattr(image, "read"):
            # File-like object (Django UploadedFile)
            pil_image = stack.enter_context(PILImage.open(image))
            pil_image = pil_image.convert("RGB")
        else:
            # Assume it's already a PIL Image
            pil_image = image.convert("RGB")

        with torch.no_grad():
            image_input = preprocess(pil_image).unsqueeze(0).to(device)
            image_features = model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)

        return image_features.cpu().numpy()[0].tolist()


@ratelimit(key="ip", rate="1000/h", method=["GET", "POST"])  # 16/min average
@ratelimit(key="ip", rate="100/5m", method=["GET", "POST"])  # 20/min burst
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

    # Validate query length
    if len(query) > MAX_TEXT_QUERY_LENGTH:
        return JsonResponse(
            {
                "success": False,
                "error": f"Query too long. Maximum {MAX_TEXT_QUERY_LENGTH} characters.",
            },
            status=400,
        )

    # Get search and pagination parameters
    try:
        limit = min(int(request.GET.get("pagelimit", 20)), 100)
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "Invalid pagination parameters"}, status=400
        )
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
        try:
            query_embedding = _get_text_embedding(query)
            query_dimension = len(query_embedding)
        except Exception as e:
            logger.warning(f"Text embedding generation failed: {type(e).__name__}")
            return JsonResponse(
                {"success": False, "error": "Could not process search query"},
                status=400,
            )

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
            count_sql = sql.SQL("""
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
            """).format(where_clause=sql.SQL(where_clause))
            cursor.execute(count_sql, where_params)
            total_count = cursor.fetchone()[0]

            # Raw SQL query for cosine similarity
            query_sql = sql.SQL("""
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
                ORDER BY embedding::vector <=> %s::vector, id ASC  -- ← ADD ", id ASC"
                LIMIT %s
                OFFSET %s
            """).format(where_clause=sql.SQL(where_clause))

            # Pass embedding as parameter - pgvector accepts array format
            query_params = (
                [query_embedding] + where_params + [query_embedding, limit, offset]
            )

            cursor.execute(query_sql, query_params)
            results = cursor.fetchall()

        # Format results - Fetch all images in one query to avoid N+1 problem
        search_results = []
        image_ids = [row[0] for row in results]
        images_dict = {
            img.id: img
            for img in Image.objects.select_related("collection__source").filter(
                id__in=image_ids
            )
        }

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
            image = images_dict.get(image_id)
            if not image:
                # Skip if image was deleted between query and retrieval
                continue

            result = {
                "id": image_id,
                "title": title,
                "permalink": permalink,
                "thumbnail": image.thumbnail if image.thumbnail else permalink,
                "original_date": str(original_date) if original_date else None,
                "edtf_date": str(edtf_date) if edtf_date else None,
                "distance": float(distance),
                "similarity": 1.0 - float(distance),  # Convert distance to similarity
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

    except DatabaseError as e:
        logger.error(f"Database error in semantic search: {e}", exc_info=True)
        return JsonResponse(
            {"success": False, "error": "Database query failed. Please try again."},
            status=500,
        )
    except Exception:
        logger.exception("Unexpected error in semantic search")
        return JsonResponse(
            {"success": False, "error": "An unexpected error occurred."},
            status=500,
        )


@ratelimit(key="ip", rate="1000/h", method=["GET", "POST"])  # 16/min average
@ratelimit(key="ip", rate="100/5m", method=["GET", "POST"])  # 20/min burst
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
    georeferenced_status = request.GET.get(
        "georeferenced", "all"
    )  # 'all', 'yes', or 'none'

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
        with connection.cursor() as cursor:
            # Build WHERE conditions based on georeferenced filter
            where_conditions = ["embedding IS NOT NULL", "id != %s"]
            where_params = [target_image.id]

            if georeferenced_status == "yes":
                where_conditions.append(
                    "EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"
                )
            elif georeferenced_status == "none":
                where_conditions.append(
                    "NOT EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = images_image.id)"
                )

            where_clause = " AND ".join(where_conditions)

            # Get total count for pagination
            count_sql = sql.SQL("""
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
            """).format(where_clause=sql.SQL(where_clause))
            cursor.execute(count_sql, where_params)
            total_count = cursor.fetchone()[0]

            # SQL-level pagination - only fetch the IDs we need for this page
            query_sql = sql.SQL("""
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
            """).format(where_clause=sql.SQL(where_clause))
            cursor.execute(
                query_sql,
                [target_image.embedding] + where_params + [per_page, offset],
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

        page_obj = SimplePage(ordered_images_on_page, page_number, total_pages, total_count, per_page)

        context = {
            "target_image": target_image,
            "page_obj": page_obj,
            "total_similar_count": total_count,
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


@ratelimit(key="ip", rate="1000/h", method=["GET", "POST"])  # 16/min average
@ratelimit(key="ip", rate="100/5m", method=["GET", "POST"])  # 20/min burst
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

    # Validate query length
    if len(query) > MAX_TEXT_QUERY_LENGTH:
        return JsonResponse(
            {
                "success": False,
                "error": f"Query too long. Maximum {MAX_TEXT_QUERY_LENGTH} characters.",
            },
            status=400,
        )

    # Get search and pagination parameters
    try:
        limit = min(int(request.GET.get("pagelimit", 20)), 100)
        page = max(int(request.GET.get("page", 1)), 1)
        distance_threshold = float(request.GET.get("threshold", 0.7))

        # Convert years here
        start_year_str = request.GET.get("start_year")
        end_year_str = request.GET.get("end_year")
        start_year = int(start_year_str) if start_year_str else None
        end_year = int(end_year_str) if end_year_str else None
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "Invalid numeric parameters"}, status=400
        )

    offset = (page - 1) * limit
    georeferenced_only = (
        request.GET.get("georeferenced_only", "false").lower() == "true"
    )
    non_georeferenced_only = (
        request.GET.get("non_georeferenced_only", "false").lower() == "true"
    )

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
        # Build SQL WHERE conditions for all filters
        # This is much more efficient than loading IDs into memory
        sql_where_conditions = [
            "c.public = true",
            "s.public = true",
            "i.duplicate_of_id IS NULL",
        ]
        sql_params = {
            "query": query,
            "threshold": distance_threshold,
            "limit": limit,
            "offset": offset,
        }

        # Georeferenced filtering
        if georeferenced_only:
            sql_where_conditions.append(
                "EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = i.id)"
            )
        elif non_georeferenced_only:
            sql_where_conditions.append(
                "NOT EXISTS (SELECT 1 FROM images_georeference g WHERE g.image_id = i.id)"
            )

        # Year filtering
        if start_year:
            sql_where_conditions.append(
                "(i.start_decdate >= %(start_year)s OR i.fuzzy_start_decdate >= %(start_year)s)"
            )
            sql_params["start_year"] = start_year

        if end_year:
            sql_where_conditions.append(
                "(i.end_decdate <= %(end_year)s OR i.fuzzy_end_decdate <= %(end_year)s)"
            )
            sql_params["end_year"] = end_year

        # Subject filtering
        if no_subjects:
            sql_where_conditions.append(
                "NOT EXISTS (SELECT 1 FROM images_subjectmapping sm WHERE sm.image_id = i.id)"
            )
        else:
            if with_subject_ids:
                for idx, subject_id in enumerate(with_subject_ids):
                    param_name = f"with_subject_{idx}"
                    sql_where_conditions.append(
                        f"EXISTS (SELECT 1 FROM images_subjectmapping sm WHERE sm.image_id = i.id AND sm.subject_id = %({param_name})s)"
                    )
                    sql_params[param_name] = subject_id

            if without_subject_ids:
                sql_where_conditions.append(
                    "i.id NOT IN (SELECT image_id FROM images_subjectmapping WHERE subject_id = ANY(%(without_subject_ids)s))"
                )
                sql_params["without_subject_ids"] = without_subject_ids

        where_clause = " AND ".join(sql_where_conditions)

        # 2. Use Raw SQL for the complex trigram query for performance and control
        with connection.cursor() as cursor:
            # First, get total count of results that meet the threshold
            where_clause = " AND ".join(sql_where_conditions)

            count_sql = sql.SQL("""
                SELECT COUNT(i.id)
                FROM images_image i
                JOIN images_collection c ON i.collection_id = c.id
                JOIN images_source s ON c.source_id = s.id
                LEFT JOIN LATERAL (
                    SELECT MIN(%(query)s <<-> c.text) as best_comment_distance
                    FROM images_comment c
                    WHERE c.image_id = i.id
                ) comment_match ON true
                LEFT JOIN LATERAL (
                    SELECT MIN(%(query)s <<-> g.confidence_notes) as best_geo_distance
                    FROM images_georeference g
                    WHERE g.image_id = i.id
                    AND g.confidence_notes != ''
                ) geo_match ON true
                LEFT JOIN LATERAL (
                    SELECT MIN(%(query)s <<-> ag.confidence_notes) as best_aerial_distance
                    FROM images_aerialgeoreference ag
                    WHERE ag.image_id = i.id
                    AND ag.confidence_notes != ''
                ) aerial_match ON true
                WHERE
                    {where_clause}
                    AND LEAST(
                        COALESCE(%(query)s <<-> i.title, 1.0),
                        COALESCE(%(query)s <<-> i.description, 1.0),
                        COALESCE(comment_match.best_comment_distance, 1.0),
                        COALESCE(geo_match.best_geo_distance, 1.0),
                        COALESCE(aerial_match.best_aerial_distance, 1.0)
                    ) < %(threshold)s
            """).format(where_clause=sql.SQL(where_clause))

            cursor.execute(count_sql, sql_params)
            total_count = cursor.fetchone()[0]

            # Now, get the paginated results
            page_query = sql.SQL("""
                SELECT
                    i.id, i.title, i.permalink, i.original_date, i.edtf_date,
                    LEAST(
                        COALESCE(%(query)s <<-> i.title, 1.0),
                        COALESCE(%(query)s <<-> i.description, 1.0),
                        COALESCE(comment_match.best_comment_distance, 1.0),
                        COALESCE(geo_match.best_geo_distance, 1.0),
                        COALESCE(aerial_match.best_aerial_distance, 1.0)
                    ) as distance
                FROM images_image i
                JOIN images_collection c ON i.collection_id = c.id
                JOIN images_source s ON c.source_id = s.id
                LEFT JOIN LATERAL (
                    SELECT MIN(%(query)s <<-> c.text) as best_comment_distance
                    FROM images_comment c
                    WHERE c.image_id = i.id
                ) comment_match ON true
                LEFT JOIN LATERAL (
                    SELECT MIN(%(query)s <<-> g.confidence_notes) as best_geo_distance
                    FROM images_georeference g
                    WHERE g.image_id = i.id
                    AND g.confidence_notes != ''
                ) geo_match ON true
                LEFT JOIN LATERAL (
                    SELECT MIN(%(query)s <<-> ag.confidence_notes) as best_aerial_distance
                    FROM images_aerialgeoreference ag
                    WHERE ag.image_id = i.id
                    AND ag.confidence_notes != ''
                ) aerial_match ON true
                WHERE
                    {where_clause}
                    AND LEAST(
                        COALESCE(%(query)s <<-> i.title, 1.0),
                        COALESCE(%(query)s <<-> i.description, 1.0),
                        COALESCE(comment_match.best_comment_distance, 1.0),
                        COALESCE(geo_match.best_geo_distance, 1.0),
                        COALESCE(aerial_match.best_aerial_distance, 1.0)
                    ) < %(threshold)s
                ORDER BY distance ASC, i.id ASC
                LIMIT %(limit)s OFFSET %(offset)s
            """).format(where_clause=sql.SQL(where_clause))
            cursor.execute(page_query, sql_params)
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
                "thumbnail": image.thumbnail if image.thumbnail else permalink,
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

    except DatabaseError as e:
        logger.error(f"Database error in text search: {e}", exc_info=True)
        return JsonResponse(
            {"success": False, "error": "Search query failed. Please try again."},
            status=500,
        )
    except Exception:
        logger.exception("Unexpected error in text search")
        return JsonResponse(
            {"success": False, "error": "An unexpected error occurred."}, status=500
        )


@ratelimit(key="ip", rate="100/h", method=["POST"])  # Stricter for image processing
@ratelimit(key="ip", rate="20/5m", method=["POST"])  # Lower burst
@login_required
@require_http_methods(["POST"])
def reverse_image_search(request):
    """API endpoint for reverse image search using CLIP embeddings - requires authentication"""
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

    if not CLIP_AVAILABLE:
        return JsonResponse(
            {
                "success": False,
                "error": "Reverse image search not available. CLIP dependencies not installed.",
            },
            status=503,
        )

    # Check if an image was uploaded
    if "image" not in request.FILES:
        return JsonResponse(
            {"success": False, "error": "No image file provided"}, status=400
        )

    uploaded_file = request.FILES["image"]

    # Check file size
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        return JsonResponse({"success": False, "error": "File too large"}, status=400)

    # Validate file type
    if not uploaded_file.content_type.startswith("image/"):
        return JsonResponse(
            {"success": False, "error": "Uploaded file must be an image"}, status=400
        )

    # Get search and pagination parameters
    try:
        limit = min(int(request.POST.get("pagelimit", 20)), 100)
        page = max(int(request.POST.get("page", 1)), 1)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "Invalid pagination parameters"}, status=400
        )
    offset = (page - 1) * limit

    georeferenced_only = (
        request.POST.get("georeferenced_only", "false").lower() == "true"
    )
    non_georeferenced_only = (
        request.POST.get("non_georeferenced_only", "false").lower() == "true"
    )

    # Year filtering parameters
    start_year = request.POST.get("start_year")
    end_year = request.POST.get("end_year")

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
    with_subjects_str = request.POST.get("with_subjects")
    without_subjects_str = request.POST.get("without_subjects")
    no_subjects = request.POST.get("no_subjects", "false").lower() == "true"

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
        # Sanitize and validate the image (defense-in-depth security)
        try:
            sanitized_image = _sanitize_image(uploaded_file)
        except ValueError as e:
            # ValueError contains our custom error messages from sanitization
            return JsonResponse(
                {"success": False, "error": str(e)},
                status=400,
            )
        except Exception as e:
            logger.warning(f"Image sanitization error: {type(e).__name__}")
            return JsonResponse(
                {"success": False, "error": "Failed to process uploaded image"},
                status=400,
            )

        # Generate embedding from sanitized image
        try:
            query_embedding = _get_image_embedding(sanitized_image)
        except Exception as e:
            logger.warning(f"Image embedding generation failed: {type(e).__name__}")
            return JsonResponse(
                {"success": False, "error": "Could not generate image embedding"},
                status=400,
            )

        query_dimension = len(query_embedding)

        # Check dimension compatibility with database
        sample_embedding = None
        expected_dimension = None

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

        # Check dimension compatibility
        if expected_dimension and query_dimension != expected_dimension:
            return JsonResponse(
                {
                    "success": False,
                    "error": f"Model dimension mismatch. Database contains {expected_dimension}D embeddings, but current model produces {query_dimension}D embeddings.",
                },
                status=400,
            )

        # Use raw SQL for vector similarity search
        with connection.cursor() as cursor:
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
                where_params["start_year"] = start_year

            if end_year is not None:
                where_conditions.append(
                    "(end_decdate <= %s OR fuzzy_end_decdate <= %s)"
                )
                where_params["end_year"] = end_year

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
            count_sql = sql.SQL("""
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
            """).format(where_clause=sql.SQL(where_clause))
            cursor.execute(count_sql, where_params)
            total_count = cursor.fetchone()[0]

            # Raw SQL query for cosine similarity
            query_sql = sql.SQL("""
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
                ORDER BY embedding::vector <=> %s::vector, id ASC  -- ← ADD ", id ASC"
                LIMIT %s
                OFFSET %s
            """).format(where_clause=sql.SQL(where_clause))

            # Pass embedding as parameter - pgvector accepts array format
            query_params = (
                [query_embedding] + where_params + [query_embedding, limit, offset]
            )

            cursor.execute(query_sql, query_params)
            results = cursor.fetchall()

        # Format results - Fetch all images in one query to avoid N+1 problem
        search_results = []
        image_ids = [row[0] for row in results]
        images_dict = {
            img.id: img
            for img in Image.objects.select_related("collection__source").filter(
                id__in=image_ids
            )
        }

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
            image = images_dict.get(image_id)
            if not image:
                # Skip if image was deleted between query and retrieval
                continue

            result = {
                "id": image_id,
                "title": title,
                "permalink": permalink,
                "thumbnail": image.thumbnail if image.thumbnail else permalink,
                "original_date": str(original_date) if original_date else None,
                "edtf_date": str(edtf_date) if edtf_date else None,
                "distance": float(distance),
                "similarity": 1.0 - float(distance),  # Convert distance to similarity
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

        return JsonResponse(
            {
                "success": True,
                "query": "reverse_image_search",
                "results": search_results,
                "count": total_count,
                "page": page,
                "limit": limit,
                "search_type": "reverse_image",
            }
        )

    except DatabaseError as e:
        logger.error(f"Database error in reverse image search: {e}", exc_info=True)
        return JsonResponse(
            {"success": False, "error": "Database query failed. Please try again."},
            status=500,
        )
    except Exception:
        logger.exception("Unexpected error in reverse image search")
        return JsonResponse(
            {"success": False, "error": "An unexpected error occurred."},
            status=500,
        )
