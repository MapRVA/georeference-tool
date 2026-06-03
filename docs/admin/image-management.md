# Image Management

## Duplicates

Once a collection has been imported it's common to find duplicate images in it.
Deciding two images are duplicates is something of an art rather than a science.
If the only difference between two images is any of the following:

- color (e.g., beige vs. greyscale scans of black and white images)
- crop
- very minor perspective change, less than a degree or two and not creating any 
- resolution

In general, we try to respect the original collection's extent and import all of the images from it.
By marking duplicates, we can declutter the Yesterdays interface and prevent users from georeferencing the same images twice.

### How to Mark Duplicates

1. For any set of duplicates, you must choose which image is highest quality and therefore remains as the primary image for that set in the Yesterdays interface. Note the ID of this image (number in its URL).
2. For the other images in the duplicate set, navigate to their admin pages and type the primary image's ID into their "duplicate of" field. The primary image should appear as an option in the dropdown. Click the primary image once it appears in that dropdown.
3. Save your change, and navigate to the primary image's detail page. You should now see its duplicate(s) listed below the fold.

## Spelling and Grammar Corrections

In general, we discourage admins from editing image metadata from the source, preferring to display image titles, descriptions, and other descriptions as faithfully as possible.

In the future we intend to add more options for users to submit corrections to the date, and perhaps even title, of images.
