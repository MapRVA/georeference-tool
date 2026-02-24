# Activity

This endpoint gives you a live feed of recent activity on Yesterdays. For overall numbers, see [statistics](statistics.md).

## Activity feed

```
GET /api/v2/activity/
```

Returns a stream of recent activity on the site, including georeference contributions, comments, and milestones.

### Example request

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/activity/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/activity/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/activity/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

### Example response

```json
[
    {
        "type": "georeference_group",
        "timestamp": "2026-02-23T17:57:43Z",
        "data": {
            "user": "John Pole",
            "count": 4,
            "started_at": "2026-02-23T17:56:02Z",
            "ended_at": "2026-02-23T17:57:43Z",
            "images": [
                {
                    "id": 28656,
                    "title": "2705 - 2703 - 2701 E. Grace St.",
                    "thumbnail": "https://cdn.maprva.org/eea94aadbb05db2f4a54_thumb"
                },
                {
                    "id": 26221,
                    "title": "13 - 17 E. Broad St.",
                    "thumbnail": "https://cdn.maprva.org/58d41134f2b0a2057256_thumb"
                }
            ]
        }
    },
    {
        "type": "comment",
        "timestamp": "2026-02-20T16:59:14Z",
        "data": {
            "user": "John Pole",
            "text": "The sculptor calls this piece \"The Case of the Missing Executive\" on his own website",
            "image_id": 8151,
            "image_title": "Corporate Presence Sculpture"
        }
    },
    {
        "type": "user_milestone",
        "timestamp": "2026-02-20T01:58:16Z",
        "data": {
            "user": "whwilson",
            "count": 15
        }
    },
    {
        "type": "sitewide_milestone",
        "timestamp": "2026-02-23T17:57:43Z",
        "data": {
            "count": 9000
        }
    }
]
```

!!! info
    The activity feed returns a flat array (not a paginated response).
    Use the `before` parameter to page through older events.
    When the response contains fewer events than `limit` (or is empty), you've reached the end of the feed.

### Event types

The feed contains four types of events:

#### `georeference_group`

Consecutive georeferences by the same user, grouped together as long as each one is made within 3 hours of the last.
This reduces noise in the feed when someone georeferences many images in one session.

| Field | Type | Description |
|---|---|---|
| `user` | string | OpenStreetMap username of the contributor |
| `count` | integer | Number of georeferences in this group |
| `started_at` | string | When the first georeference was made |
| `ended_at` | string | When the last georeference was made |
| `images` | array | The images that were georeferenced (id, title, thumbnail) |

#### `comment`

A comment left on an image.

| Field | Type | Description |
|---|---|---|
| `user` | string | OpenStreetMap username of the commenter |
| `text` | string | Comment text |
| `image_id` | integer | ID of the image |
| `image_title` | string | Title of the image |

#### `user_milestone`

A contributor reached a georeferencing milestone (5, 15, 50, 100, 250, etc.).
The exact milestones are set by the site administrator and are subject to change.

| Field | Type | Description |
|---|---|---|
| `user` | string | OpenStreetMap username of the contributor |
| `count` | integer | The milestone reached |

#### `sitewide_milestone`

The site as a whole reached a total georeferencing milestone (100, 250, 500, 1000, etc.).
The exact milestones are set by the site administrator and are subject to change.

| Field | Type | Description |
|---|---|---|
| `count` | integer | The milestone reached |

### Query parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `before` | string | — | ISO 8601 timestamp. Return only events before this time. Use this for pagination by passing the `timestamp` of the last event you received. |
| `types` | string | all | Comma-separated list of event types to include: `georeference_group`, `comment`, `user_milestone`, `sitewide_milestone`. |
| `limit` | integer | 20 | Number of events to return (max 100). |

### Examples

#### Paginating through the feed

Fetch the first page:

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/activity/"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/activity/")
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/activity/") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

Then use the `timestamp` of the last event to fetch the next page:

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/activity/?before=2026-02-20T01:58:16Z"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/activity/", params={
        "before": "2026-02-20T01:58:16Z",
    })
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/activity/") |>
      req_url_query(before = "2026-02-20T01:58:16Z") |>
      req_perform()
    data <- resp_body_json(resp)
    ```

#### Filtering by type

Show only comments and milestones:

=== "curl"

    ```bash
    curl "https://yesterdays.maprva.org/api/v2/activity/?types=comment,user_milestone"
    ```

=== "Python"

    ```python
    import requests

    response = requests.get("https://yesterdays.maprva.org/api/v2/activity/", params={
        "types": "comment,user_milestone",
    })
    data = response.json()
    ```

=== "R"

    ```r
    library(httr2)

    resp <- request("https://yesterdays.maprva.org/api/v2/activity/") |>
      req_url_query(types = "comment,user_milestone") |>
      req_perform()
    data <- resp_body_json(resp)
    ```
