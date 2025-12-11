import json
from pathlib import Path

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Func
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from ..models import Image

# Global variables for CLIP model (loaded on first use)
_clip_model = None
_clip_preprocess = None
_clip_device = None


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
                    "thumbnail": image.thumbnail if image.thumbnail else permalink,
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
    georeferenced_status = request.GET.get(
        "georeferenced", "all"
    )  # 'all', 'yes', or 'none'

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
                    "thumbnail": image.thumbnail
                    if image.thumbnail
                    else image.permalink,
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
                SELECT COUNT(i.id)
                FROM images_image i
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
                    i.id = ANY(%(ids)s)
                    AND LEAST(
                        COALESCE(%(query)s <<-> i.title, 1.0),
                        COALESCE(%(query)s <<-> i.description, 1.0),
                        COALESCE(comment_match.best_comment_distance, 1.0),
                        COALESCE(geo_match.best_geo_distance, 1.0),
                        COALESCE(aerial_match.best_aerial_distance, 1.0)
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
                    i.id, i.title, i.permalink, i.original_date, i.edtf_date,
                    LEAST(
                        COALESCE(%(query)s <<-> i.title, 1.0),
                        COALESCE(%(query)s <<-> i.description, 1.0),
                        COALESCE(comment_match.best_comment_distance, 1.0),
                        COALESCE(geo_match.best_geo_distance, 1.0),
                        COALESCE(aerial_match.best_aerial_distance, 1.0)
                    ) as distance
                FROM images_image i
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
                    i.id = ANY(%(ids)s)
                    AND LEAST(
                        COALESCE(%(query)s <<-> i.title, 1.0),
                        COALESCE(%(query)s <<-> i.description, 1.0),
                        COALESCE(comment_match.best_comment_distance, 1.0),
                        COALESCE(geo_match.best_geo_distance, 1.0),
                        COALESCE(aerial_match.best_aerial_distance, 1.0)
                    ) < %(threshold)s
                ORDER BY distance ASC
                LIMIT %(limit)s OFFSET %(offset)s
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

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Text search failed: {str(e)}"}, status=500
        )
