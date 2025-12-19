# Searching

## Semantic Search

Yesterdays provides a "semantic search" feature on [the search page](https://yesterdays.maprva.org/search/), which allows the user to search based on the **content** of the images rather than any textual metadata. This uses a [CLIP](https://en.wikipedia.org/wiki/Contrastive_Language-Image_Pre-training) model, allowing users to search by describing what the images are of.

Try out searches like:

- firefighters responding to the scene
- stained-glass windows
- truck on a highway
- etc.

### Find Similar Images

On an image page or subject page, there is a button to view "similar" images to that image or subject.
This list uses the same CLIP model described above, providing images that look similar to the given image or set of images.

## Text Search

On [the search page](https://yesterdays.maprva.org/search/), there is also a classic text search, which indexes:

- Image titles (from source)
- Image descriptions (from source)
- Comments and georeference notes
