# Search

Yesterdays offers two search endpoints:

- **Semantic search** interprets textual input even if the exact words don't appear in the image's title or description. For example, searching "church steeple at sunset" will find visually similar images.
- **Text search** searches across titles, descriptions, comments, and georeference notes for text that closely resembles your query.

Both endpoints return the same result format.

## Semantic search

```
GET /api/v2/search/semantic/?q={query}
```

Uses a [CLIP](https://en.wikipedia.org/wiki/Contrastive_Language-Image_Pre-training) model to encode your query into a vector and find images whose visual content is most similar.

!!! info
    Semantic search only works on images that have been processed by our CLIP model. Newly added images may not immediately appear in search results.

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/search/semantic/?q=church+on+a+hill"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/search/semantic/", params={
        "q": "church on a hill",
    })
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/search/semantic/") |>
      req_url_query(q = "church on a hill") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

### Example response

```json
{
    "count": 234,
    "page": 1,
    "page_size": 20,
    "query": "church on a hill",
    "results": [
        {
            "id": 657,
            "title": "St. Johns Church area 1",
            "permalink": "https://yesterdays.maprva.org/657/",
            "thumbnail": "https://cdn.maprva.org/71086e03d2fefa626a0e_thumb",
            "original_date": "1965",
            "date_display": "1965",
            "similarity": 0.8341,
            "collection": {
                "id": 125,
                "name": "1965 Richmond Esthetic Survey and Historic Building Survey",
                "slug": "1965-esthetic-survey",
                "source_name": "Library of Virginia"
            },
            "detail_url": "https://yesterdays.maprva.org/api/v2/images/657/"
        }
    ]
}
```

## Text search

```
GET /api/v2/search/text/?q={query}
```

Uses PostgreSQL trigram word similarity to search across multiple text fields for each image:

- Image title
- Image description
- Community comments
- Georeference notes

Results are ranked by how closely the query matches, with the best matches first.

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/search/text/?q=broad+street"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/search/text/", params={
        "q": "broad street",
    })
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/search/text/") |>
      req_url_query(q = "broad street") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

### Example response

```json
{
    "count": 89,
    "page": 1,
    "page_size": 20,
    "query": "broad street",
    "results": [
        {
            "id": 1067,
            "title": "E. Broad Street",
            "permalink": "https://yesterdays.maprva.org/1067/",
            "thumbnail": "https://cdn.maprva.org/09035fe9fe8c4411ccfc_thumb",
            "original_date": "1941-1949",
            "date_display": "1941-1949",
            "similarity": 0.9412,
            "collection": {
                "id": 37,
                "name": "Mary Wingfield Scott Photograph Collection",
                "slug": "mary-wingfield-scott-photograph-collection",
                "source_name": "The Valentine"
            },
            "detail_url": "https://yesterdays.maprva.org/api/v2/images/1067/"
        }
    ]
}
```

### Text search parameters

| Parameter   | Type   | Default | Description |
|-------------|--------|---------|-------------|
| `threshold` | number | 0.7     | Distance threshold (0 to 1). Lower values return fewer, more precise matches; higher values return more results with looser matching. |

## Shared parameters

Both search endpoints accept these parameters:

### Query

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `q`       | string | Search query (required, max 500 characters) |

### Pagination

| Parameter   | Type    | Default | Description |
|-------------|---------|---------|-------------|
| `page`      | integer | 1       | Page number |
| `page_size` | integer | 20      | Results per page (max 100) |

### Filters

| Parameter       | Type    | Description |
|-----------------|---------|-------------|
| `georeferenced` | boolean | `true` for georeferenced images only, `false` for un-georeferenced |
| `year_min`      | integer | Include images whose date range overlaps with or follows this year |
| `year_max`      | integer | Include images whose date range overlaps with or precedes this year |
| `source`        | integer | Filter by source ID |
| `collection`    | integer | Filter by collection ID |
| `subject`       | integer | Filter by subject ID |

### Example: combining search with filters

Find images matching "hotel" from the Library of Virginia, taken before 1920:

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/search/text/?q=hotel&source=1&year_max=1920"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/search/text/", params={
        "q": "hotel",
        "source": 1,
        "year_max": 1920,
    })
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/search/text/") |>
      req_url_query(q = "hotel", source = 1, year_max = 1920) |>
      req_perform()
    data <- resp_body_json(resp)
    ```

## Response format

Search endpoints use a different pagination format than other list endpoints, returning `page` and `page_size` instead of `next` and `previous` links.

Both endpoints return a response with the following structure:

| Field | Type | Description |
|---|---|---|
| `count` | integer | Total number of matching results |
| `page` | integer | Current page number |
| `page_size` | integer | Number of results per page |
| `query` | string | The search query that was submitted |
| `results` | array | List of matching images (see fields below) |

### Result fields

| Field | Type | Description |
|---|---|---|
| `id` | integer | Image ID |
| `title` | string | Image title |
| `permalink` | string | Link to the image on the Yesterdays website |
| `thumbnail` | string | URL to a thumbnail |
| `original_date` | string | Date as recorded by the source |
| `date_display` | string | Human-friendly date display |
| `similarity` | number | Similarity score from 0 to 1 (higher is more similar). Scores are not directly comparable between semantic and text search. |
| `collection` | object | Collection info (id, name, slug, source_name) |
| `detail_url` | string | API link to the full image detail |
