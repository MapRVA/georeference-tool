# Collections

Collections group related images within a [source](sources.md).
For example, [*Cook Photograph Collection*](https://yesterdays.maprva.org/browse/the-valentine/cook-photograph-collection/) is one of several collections from The Valentine.

There are no "subcollections" in Yesterdays.
Just sources and collections.

## List all collections

```
GET /api/v2/collections/
```

Returns a paginated list of all public collections.

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/collections/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/collections/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/collections/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

### Example response

```json
{
    "count": 49,
    "next": null,
    "previous": null,
    "results": [
        {
            "id": 118,
            "name": "Cook Photograph Collection",
            "slug": "cook-photograph-collection",
            "url": "https://valentine.rediscoverysoftware.com/MADetailG.aspx?rID=PHC0047&db=group&dir=VALARCH",
            "description": "This collection of more than 10,0000 glass-plate and film negatives...",
            "source": {
                "id": 2,
                "name": "The Valentine",
                "slug": "the-valentine"
            },
            "image_count": 1957,
            "images_url": "https://yesterdays.maprva.org/api/v2/images/?collection=118"
        }
    ]
}
```

The full response would include all 49 collections in the `results` list. This example shows just one for brevity.

## Get a single collection

```
GET /api/v2/collections/{id}/
```

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/collections/118/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/collections/118/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/collections/118/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

## Fields

| Field | Type | Description |
|---|---|---|
| `id` | integer | Unique identifier |
| `name` | string | Name of the collection |
| `slug` | string | URL-friendly name |
| `url` | string | Link to the collection in the original archive |
| `description` | string | Description of the collection |
| `source` | object | The [source](sources.md) this collection belongs to (id, name, slug) |
| `image_count` | integer | Number of images in this collection |
| `images_url` | string | API link to browse this collection's images |

## Filtering

| Parameter | Description |
|---|---|
| `source` | Filter by source ID (e.g., `?source=2`) |
| `slug` | Filter by exact slug |

## Ordering

| Parameter | Description |
|---|---|
| `name` | Sort alphabetically by collection name |
| `source__name` | Sort by source name, then collection name (default) |
