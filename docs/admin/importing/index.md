# Importing Images

!!! warning
    It is very important that you respect image licenses when importing from external sources.
    Please work with site administrators to ensure adherence to copyright restrictions.

## Overview

Here is an overview of the image import process.

1. A collection of images is provided by a source institution.
2. Each image's metadata is processed into a standard format for Yesterdays.
3. Each image is then uploaded to Yesterdays [via our API](/dev/api/images/#import-a-new-image).
4. The Yesterdays server processes the images, such as generating thumbnails.
5. The images are ready for users to discover.

You may optionally set a collection to be private, which hides it from being displayed on your Yesterdays site.

## Creating Collections

Yesterdays has a [three-tier organization system](/usage/organization/): sources, collections, and images.
In order to import images, you must create the source and the collection within that source that you'll import them into.

## Image Metadata

!!! note "This is a summary"
    Please see our documentation for [Yesterdays Desktop](/admin/importing/desktop/) or the [image upload API](/dev/api/images/#import-a-new-image) for more details.

Images must have:

- A title,
- an [EDTF](https://www.loc.gov/standards/datetime/) representation of when they were taken,
- a permalink to their source information,
- a permalink to the image itself hosted by the source.

Images may optionally have:

- A description,
- a source-specific reference ID,
- a license title,
- a link to its license,
- creator information.

## After Import

After importing a collection, you will work with site administrators to:

- mark any duplicates,
- mark any images as "will not georeference" or "from above" as appropriate,
- add subjects to your images.
