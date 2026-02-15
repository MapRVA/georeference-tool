# Searching

## Semantic Search

Yesterdays provides a "semantic search" feature on [the search page](https://yesterdays.maprva.org/search/), which allows the user to search based on the **content** of the images rather than any textual metadata. This uses a [CLIP](https://en.wikipedia.org/wiki/Contrastive_Language-Image_Pre-training) model, allowing users to search by describing what the images are of.

Try out searches like:

- [firefighters responding to the scene](https://yesterdays.maprva.org/search/?q=firefighters+responding+to+the+scene&mode=semantic)
- [stained-glass windows](https://yesterdays.maprva.org/search/?q=stained-glass+windows&mode=semantic)
- [truck on a highway](https://yesterdays.maprva.org/search/?q=truck+on+a+highway&mode=semantic)
- etc.

### Find Similar Images

On an image page or subject page, there is a button to view "similar" images to that image or subject.
This list uses the same CLIP model described above, providing images that look similar to the given image or set of images.

## Text Search

On [the search page](https://yesterdays.maprva.org/search/), there is also a classic text search, which indexes:

- Image titles (from source)
- Image descriptions (from source)
- Comments and georeference notes

## Reverse Image Search

!!! info
    Reverse image search is currently only available to logged-in users.
    It is free and easy to make an account with OpenStreetMap!

The reverse image search feature allows you to upload your own image, and find similar images in Yesterdays. Currently, only JPEG, PNG, GIF, and WEBP image formats are supported.

You can upload your image by doing any of the following:

- clicking on the "Select File" button to select an image file from your filesystem,
- dragging an image file into the upload area from e.g. your file browser, or
- pasting an image from your clipboard using CTRL+V or CMD+V

Images are searched using the same CLIP model described in the Semantic Search section above.
