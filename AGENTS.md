This repository is a Django project, powering a community effort to catalogue and georeference thousands of images of my city. Most of these are old photographs, stretching all the way back to the mid-1800s.

Besides placing images on the map (our core goal), this app provides a growing range of features:
- users can login using OpenStreetMap accounts
- favorite and share images
- tag images with their "subjects"
- search image descriptions, or their content ("semantic" search) using a CLIP model
- ...and much more!

Alongside Django, this project uses Vite (managed by bun) to bundle JavaScript and CSS assets from /assets. The application makes heavy use of MapLibre, and Alpine.js is universally available so it's best to follow Alpine.js best practices where we can.

**Important**: When creating new page-specific JavaScript files in `assets/js/pages/`, you must also add them as entry points in `vite.config.js` under `rollupOptions.input`. Otherwise, the asset will work in development but fail in production with a 500 error.

A public read-only REST API lives in the `api/` app, served at `/api/v2/`. It uses Django REST Framework, django-rest-framework-gis, and django-filter. The API has no models of its own — it exposes data from `images`, `subjects`, and `activity` through serializers, viewsets, and filter classes in `api/serializers.py`, `api/views.py`, and `api/filters.py`. When modifying models or fields in those apps, check whether the API serializers or filters need a corresponding update. API documentation lives in `docs/api/` and should be kept in sync with any endpoint changes.

Celery handles background tasks (thumbnail generation, metadata refresh) with RabbitMQ as the broker. Celery Beat schedules periodic tasks, including rate-limited refreshes of external data from Wikidata and OpenStreetMap.

We are developing this tool together. We can run Django commands in our development environment using `uv`:

`uv run manage.py makemigrations`

However, **you must ask permission before running Django commands**. Thank you.

Additionally, please follow the following coding guidelines for this project:
- refrain from adding extraneous files, including code samples or markdown summaries / plans,
- keep Python imports at the top of the file, never nested inside of functions,
- use `django.conf.settings` for configurable values rather than hardcoding them in models or views,
- templates live in `/templates/` (project-level), organized by app name (e.g., `templates/activity/`),
- custom template tags go in `<app>/templatetags/` and require a server restart to be discovered.
