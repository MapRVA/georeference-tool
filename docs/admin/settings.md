# Site Settings

An instance's site settings can be accessed at `/admin/images/sitesettings/1/change/`.

## Hompage Content

The title and subtitle as presented in the hero on the site's landing page.

## Footer

An HTML blob to be inserted into the footer of the site.
This should include links to Yesterdays source code, admin contact information, etc.

## Contact

The administrator should consider putting their email into this field.
An email is required for Yesterdays to successfully geocode user requests using the Nominatim geocoder.

## Default Map View

These are the latitude, longitude, and zoom that maps across the site, including `/map/` and maps in the georeference interfaces, default to.

## Default Search Bounding Box

These north/south/east/west values determine the bounds of data queries, such as with the geocoder.
It's valuable to limit this bounding box to the region of interest for your instance, so that when users search things like `123 Main Street` they're more likely to find the address they're looking for in their area.

## Default Subject Bounding Box

Subjects are currently updated using Postpass, which benefits from a limited search area.
This area should be wider than the search bounding box above, and encompass the area within which most subjects will be.
