# Importing Images

!!! warning
    It is very important that you respect image licenses when importing from external sources.
    As the site administrator it is your responsibility to adhere to copyright restrictions.

In general importing images into Yesterdays is a manual process and highly source-dependent.
We will add more information to this section as we continue to develop this system.

## Overview

Here is an overview of the image import process:

1. A script scrapes a collection of images from a source's website.
2. Each image's metadata is processed into standard formats for Yesterdays. If important metadata cannot be determined for an image, the import will stop and require further configuration.
3. Each image is then uploaded to your Content Delivery Network (CDN), where it will be served to your users.
4. The image's metadata, as well as its new CDN-backed link, are inserted into the Yesterdays database.
5. The images are ready for users to discover. Background tasks are queued to generate thumbnails and CLIP embeddings to make discovery easier.

You may optionally set a collection to be private, which hides it from being displayed on your Yesterdays site.

## Creating Collections

Yesterdays has a strict three-tier organization system: sources, collections, and images. In order to import an image, you must create the source, and collection within that source, to import them into.

### Precollections

Some collections of images are vast, and include many images which you might not want to import into Yesterdays. Perhaps there are hundreds of portraits or wedding photos, or perhaps a subset of the images were taken in a different region.

Whatever your reason, precollections allow you to conduct a staged import into Yesterdays. Here's how it works:

1. You import all of the photos into a precollection instead of a regular collection. The photos are hotlinked (embedded directly from their source rather than uploaded to your CDN), and viewable only in the admin panel.
2. In the admin panel, you may review each image in the collection, marking it to keep or discard. This process can be done incrementally at your convenience.
3. When you are ready, you can convert the precollection into a regular collection. Any images you marked to keep will be uploaded to your CDN as usual, and added to a collection of the same name.

## Image Metadata

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

After importing a collection, you are strongly encouraged to take the following steps:

- mark any duplicates,
- mark any images as "will not georeference" as appropriate,
- mark any images as "from above" as appropriate,
- add subjects to your images.
