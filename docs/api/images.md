# Images

Images are the heart of Yesterdays.
Most are old photographs, but they also include drawings, postcards, architectural sketches, and more.

The images endpoint has two different response formats: a list response for browsing, and a richer detail response with full metadata, georeferences, subjects, and comments.

## List images

```
GET /api/v2/images/
```

Returns a paginated list of images with basic metadata.
This response is intentionally lightweight and doesn't include georeferences, subjects, or comments.
Use the `detail_url` field to fetch the full details for any image.

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/images/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/images/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/images/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

### Example response

```json
{
    "count": 37244,
    "next": "https://yesterdays.maprva.org/api/v2/images/?page=2",
    "previous": null,
    "results": [
        {
            "id": 5934,
            "title": "N. 28th and Q Streets",
            "thumbnail": "https://cdn.maprva.org/7416452b52d0f9fdbe1c_thumb",
            "creator": "Shelton, Edith Keesee--1898-1989",
            "original_date": "9/1956",
            "date_display": "9/1956",
            "from_above": false,
            "collection": {
                "id": 39,
                "name": "Edith K. Shelton Photograph Collection",
                "slug": "edith-k-shelton-photograph-collection",
                "source_name": "The Valentine"
            },
            "georeference_status": "georeferenced",
            "detail_url": "https://yesterdays.maprva.org/api/v2/images/5934/"
        }
    ]
}
```

### List fields

| Field | Type | Description |
|---|---|---|
| `id` | integer | Unique identifier |
| `title` | string | Title of the image |
| `thumbnail` | string | URL to a thumbnail of the image |
| `creator` | string | Creator/photographer name |
| `original_date` | string | Date string as recorded by the source |
| `date_display` | string | Human-friendly date display |
| `from_above` | boolean | Whether this is a from-above (bird's-eye) image |
| `collection` | object | Collection info (id, name, slug, source_name) |
| `georeference_status` | string | One of `"available"`, `"georeferenced"`, `"duplicate"`, or `"will_not_georef"` |
| `detail_url` | string | API link to the full detail for this image |


## Filtering

| Parameter | Type | Description |
|---|---|---|
| `source` | integer | Filter by source ID |
| `collection` | integer | Filter by collection ID |
| `subject` | integer | Filter by subject ID |
| `creator` | string | Search creator name (case-insensitive, partial match) |
| `year_min` | number | Include images whose date range overlaps with or follows this year |
| `year_max` | number | Include images whose date range overlaps with or precedes this year |
| `georeferenced` | boolean | `true` for georeferenced images only, `false` for un-georeferenced |
| `from_above` | boolean | `true` for from-above images, `false` for standard images |

### Example: combining filters

Find all georeferenced images from the Valentine, taken between 1900 and 1920:

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/images/?source=2&georeferenced=true&year_min=1900&year_max=1920"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/images/", params={
        "source": 2,
        "georeferenced": "true",
        "year_min": 1900,
        "year_max": 1920,
    })
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/images/") |>
      req_url_query(source = 2, georeferenced = "true", year_min = 1900, year_max = 1920) |>
      req_perform()
    data <- resp_body_json(resp)
    ```

## Ordering

| Parameter | Description |
|---|---|
| `order` | Sort by collection order |
| `title` | Sort alphabetically by title |
| `original_date` | Sort by date |
| `created_at` | Sort by when the image was added to Yesterdays |
| `last_georeferenced_at` | Sort by when the image was most recently georeferenced |

Prefix with `-` to sort descending. For example, `ordering=original_date` gives oldest first, while `ordering=-original_date` gives newest first.

=== "curl"

    ```bash
    # Most recently georeferenced images first
    curl "https://yesterdays.maprva.org/api/v2/images/?ordering=-last_georeferenced_at"
    ```

=== "Python"

    ```python
    import requests

    # Most recently georeferenced images first
    response = requests.get("https://yesterdays.maprva.org/api/v2/images/", params={
        "ordering": "-last_georeferenced_at",
    })
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    # Most recently georeferenced images first
    resp <- request("https://yesterdays.maprva.org/api/v2/images/") |>
      req_url_query(ordering = "-last_georeferenced_at") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

Default ordering is `-order` (newest additions first).


## Get a single image

```
GET /api/v2/images/{id}/
```

Returns complete details for a single image, including its georeferences, subjects, comments, and license information.

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/images/5934/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/images/5934/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/images/5934/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

### Example response

```json
{
    "id": 5934,
    "title": "N. 28th and Q Streets",
    "permalink": "https://cdn.maprva.org/7416452b52d0f9fdbe1c",
    "thumbnail": "https://cdn.maprva.org/7416452b52d0f9fdbe1c_thumb",
    "original_url": "https://valentine.rediscoverysoftware.com/MADetailB.aspx?rID=PHC0039/-#V.91.42.2952&db=biblio&dir=VALARCH",
    "description": "35mm color slide of the intersection of N. 28th Street and Q Street in north Church Hill; image shows a horse with small wagon loaded with a bale of hay, stopped at a Yield sign; three children stand on sidewalk near horse; two-story house with siding in background; Richmond, Virginia.",
    "creator": "Shelton, Edith Keesee--1898-1989",
    "license": null,
    "original_date": "9/1956",
    "edtf_date": "1956-09",
    "date_display": "9/1956",
    "collection": {
        "id": 39,
        "name": "Edith K. Shelton Photograph Collection",
        "slug": "edith-k-shelton-photograph-collection",
        "source_name": "The Valentine"
    },
    "subjects": [
        {
            "id": 150,
            "title": "horse",
            "slug": "horse",
            "wikidata": {
                "wikidata_id": "Q726",
                "uri": "https://www.wikidata.org/entity/Q726",
                "title": "horse",
                "description": "domesticated four-footed mammal from the equine family"
            }
        }
    ],
    "from_above": false,
    "scale": null,
    "mirror": "none",
    "rotation": 0,
    "georeference_status": "georeferenced",
    "georeferences": [
        {
            "id": 5701,
            "latitude": 37.536789,
            "longitude": -77.409651,
            "direction": 136.0,
            "confidence": "medium",
            "confidence_notes": "",
            "georeferenced_by": "mhpob",
            "georeferenced_at": "2025-12-16T12:55:01Z",
            "validations": []
        }
    ],
    "from_above_georeferences": [],
    "comments": [
        {
            "id": 57,
            "text": "Other angle of #5933",
            "commented_by": "mhpob",
            "created_at": "2025-12-16T12:55:42Z"
        }
    ],
    "detail_url": "https://yesterdays.maprva.org/api/v2/images/5934/"
}
```

### Detail fields

The detail response includes all the [list fields](#list-fields), plus:

| Field                      | Type           | Description |
|----------------------------|----------------|-------------|
| `permalink`                | string         | Direct URL to the image file. If a rotation or mirror transform has been applied, this automatically points to the corrected version. |
| `original_url`             | string         | Link to the image in the original archive |
| `description`              | string         | Full description of the image |
| `license`                  | object or null | License info (display_name, permalink), or `null` if no license is available |
| `edtf_date`                | string         | Date in [EDTF](https://www.loc.gov/standards/datetime/) format, when available |
| `subjects`                 | array          | [Subjects](subjects.md) tagged in this image, with Wikidata metadata |
| `scale`                    | string         | Scale notation for maps and from-above imagery |
| `mirror`                   | string         | Mirror transform applied: `"none"`, `"h"` (horizontal), or `"v"` (vertical) |
| `rotation`                 | integer        | Clockwise rotation applied to this image: `0`, `90`, `180`, or `270` (degrees) |
| `georeferences`            | array          | Point georeferences (see below) |
| `from_above_georeferences` | array          | From-above polygon georeferences (see below) |
| `comments`                 | array          | Community comments on this image |

### Georeference objects

Each georeference in the `georeferences` array represents someone's placement of this image on the map:

| Field              | Type    | Description |
|--------------------|---------|-------------|
| `id`               | integer | Unique identifier |
| `latitude`         | number  | Latitude of the photographer's location |
| `longitude`        | number  | Longitude of the photographer's location |
| `direction`        | number  | Compass direction the camera was facing (degrees, 0 = north) |
| `confidence`       | string  | `"low"`, `"medium"`, or `"high"` |
| `confidence_notes` | string  | Explanation for the chosen confidence level |
| `georeferenced_by` | string  | OpenStreetMap username of the contributor |
| `georeferenced_at` | string  | ISO 8601 timestamp |
| `validations`      | array   | Community validations (see below) |

### From-above georeference objects

The `from_above_georeferences` array contains polygon-based georeferences for bird's-eye and from-above images:

| Field              | Type    | Description |
|--------------------|---------|-------------|
| `id`               | integer | Unique identifier |
| `polygon`          | object  | GeoJSON Polygon geometry representing the area covered |
| `confidence`       | string  | `"low"`, `"medium"`, or `"high"` |
| `confidence_notes` | string  | Explanation for the chosen confidence level |
| `georeferenced_by` | string  | OpenStreetMap username of the contributor |
| `georeferenced_at` | string  | ISO 8601 timestamp |
| `validations`      | array   | Community validations |

### Validation objects

Validations appear inside georeference objects. They represent community review of a georeference:

| Field          | Type   | Description |
|----------------|--------|-------------|
| `validation`   | string | One of `"correct"`, `"uncertain"`, or `"incorrect"` |
| `validated_by` | string | OpenStreetMap username of the reviewer |
| `notes`        | string | Optional notes from the reviewer |
| `validated_at` | string | ISO 8601 timestamp |

### Comment objects

| Field          | Type    | Description |
|----------------|---------|-------------|
| `id`           | integer | Unique identifier |
| `text`         | string  | The comment text |
| `commented_by` | string  | OpenStreetMap username of the commenter |
| `created_at`   | string  | ISO 8601 timestamp |
