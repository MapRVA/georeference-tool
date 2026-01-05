This repository is a Django project, powering a community effort to catalogue and georeference thousands of images of my city. Most of these are old photographs, stretching all the way back to the mid-1800s.

Besides placing images on the map (our core goal), this app provides a growing range of features:
- users can login using OpenStreetMap accounts
- favorite and share images
- tag images with their "subjects"
- search image descriptions, or their content ("semantic" search) using a CLIP model
- ...and much more!

Alongside Django, this project uses Vite (managed by bun) to bundle JavaScript and CSS assets from /assets. The application makes heavy use of MapLibre, and Alpine.js is universally available so it's best to follow Alpine.js best practices where we can.

We are developing this tool together. We can run Django commands in our development environment using `uv`:

`uv run manage.py makemigrations`

However, **you must ask permission before running Django commands**. Thank you.

Additionally, please follow the following coding guidelines for this project:
- refrain from adding extraneous files, including code samples or markdown summaries / plans,
- keep Python imports at the top of the file, never nested inside of functions.
