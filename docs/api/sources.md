# Sources

Sources represent the institutions — libraries, museums, archives — that contributed images to Yesterdays.
For example, the Library of Congress and the Valentine are both sources.

## List all sources

```
GET /api/v2/sources/
```

Returns a paginated list of all public sources.

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/sources/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/sources/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/sources/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

### Example response

```json
{
    "count": 2,
    "next": null,
    "previous": null,
    "results": [
        {
            "id": 1,
            "name": "Library of Virginia",
            "slug": "library-of-virginia",
            "url": "https://www.lva.virginia.gov/",
            "description": "The Library of Virginia is the archival agency and reference library for...",
            "collection_count": 3,
            "image_count": 1766,
            "collections_url": "https://yesterdays.maprva.org/api/v2/sources/1/collections/"
        },
        {
            "id": 2,
            "name": "The Valentine",
            "slug": "the-valentine",
            "url": "https://thevalentine.org/",
            "description": "The Valentine is a museum in Richmond, Virginia dedicated to...",
            "collection_count": 36,
            "image_count": 17037,
            "collections_url": "https://yesterdays.maprva.org/api/v2/sources/2/collections/"
        }
    ]
}
```

## Get a single source

```
GET /api/v2/sources/{id}/
```

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/sources/1/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/sources/1/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/sources/1/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

## List a source's collections

```
GET /api/v2/sources/{id}/collections/
```

A shortcut for listing only the collections that belong to a specific source.
This returns the same format as the [collections endpoint](collections.md).

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/sources/1/collections/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/sources/1/collections/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/sources/1/collections/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

## Fields

| Field | Type | Description |
|---|---|---|
| `id` | integer | Unique identifier |
| `name` | string | Name of the institution |
| `slug` | string | URL-friendly name |
| `url` | string | Link to the institution's website |
| `description` | string | Description of the source |
| `collection_count` | integer | Number of public collections from this source |
| `image_count` | integer | Total number of images from this source |
| `collections_url` | string | API link to this source's collections |

## Filtering

| Parameter | Description |
|---|---|
| `slug` | Filter by exact slug (e.g., `?slug=library-of-virginia`) |

## Ordering

| Parameter | Description |
|---|---|
| `name` | Sort alphabetically by name (default) |

Use `ordering=-name` to reverse the sort order.
