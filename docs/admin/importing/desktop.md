# Desktop Uploader

The Yesterdays Desktop Uploader, or simply Yesterdays Desktop, is a separate desktop application designed to make it easier to import photo collections into Yesterdays.
Yesterdays Desktop includes features such as:

- labeling a folder of photos with metadata necessary for import,
- managing uploads of photo collections using a standard schema,
- replacing photos already in Yesterdays with higher-resolution versions.

!!! warning
    You must be given access by a Yesterdays administrator to import photo collections.
    Please [contact us](/contact/) if you have a collection you would like to upload, and we will collaborate on uploading your collection.
    Thank you!

## Download Yesterdays Desktop

Yesterdays Desktop lives in its own GitHub repository, and is published under the GPLv3+ license.
We build releases for Linux, macOS, and Windows.
You are welcome to download Yesterdays Desktop here (select the correct file from the "Assets" dropdown):

[Download Yesterdays Desktop](https://github.com/MapRVA/yesterdays-desktop/releases){ .md-button .md-button--primary }

## Metadata Schema

Yesterdays Desktop uses a standardized schema for uploading images.
While this schema might seem strict, it helps us maintain a high level of confidence in the completeness and quality of the collections we host.

**Are you an individual or institution looking to contribute a collection to Yesterdays? Please [contact us](/contact/) and we can help navigate this process for you.**

### Import Folder Organization

Each image in the collection must have a 6-digit zero-padded stem, with the original extension.
Each image should be accompanied by a sidecar JSON file, with the same stem and the `.json` extension.
The stems in your import folder must be **strictly contiguous**.

```
.
├── 000001.jpg
├── 000001.json
├── 000002.png
├── 000002.json
├── 000003.tiff
├── 000003.json
└── etc.
```

Currently allowed image extensions (case-insensitive) are `jpg`, `jpeg`, `tif`, `tiff`, `png`, and `webp`.

### JSON Sidecar

The specification for the JSON sidecar format is as follows.

| Field           | Type             | Required | Notes |
|-----------------|------------------|----------|-------|
| `filename`      | string           | yes      | Must equal the paired image file's basename |
| `title`         | string           | yes      | Non-empty; sources sometimes use `"Untitled"` or similar when there truly isn't a title. |
| `original_date` | string           | yes      | Non-empty, free-text human date (e.g. `"Summer 1962"`) |
| `edtf_date`     | string           | yes      | Non-empty, [EDTF](https://www.loc.gov/standards/datetime/) format; validated server-side |
| `source_url`    | string \| null   | no       | A permanent URL to a page for this item on the source's website. |
| `description`   | string \| null   | no       | A free-form description of the work. This is where other metadata is often listed. |
| `creator`       | string \| null   | no       | Who created the image |
| `reference_id`  | string \| null   | no       | Source-specific identifier, only include if it would help a user find the original item. |
| `license_name`  | string \| null   | no       | Checked case-insensitively against `GET /api/v2/licenses/` |
| `rotation`      | integer          | yes      | Must be exactly `0`, `90`, `180`, or `270` |
| `mirror`        | string           | yes      | Must be `"none"`, `"h"`, or `"v"` |
| `subjects`      | array of strings | no       | Subject slugs, in order; absent or `null` means `[]`. There is no expectation to identify any subjects during import. |


### EDTF Format

Yesterdays uses the [Extended Date/Time Format (EDTF)](https://www.loc.gov/standards/datetime/) from the Library of Congress.

The EDTF date for each image must have a parse-able minimum and maximum.
For example, `[1865..]` (1865 or any time thereafter) would not be acceptable, but `[1865..1900]` (any time between 1865 and 1900) works.
When in doubt, please choose a bounding date that definitely encompasses the image in question.
The [oldest surviving photograph](https://en.wikipedia.org/wiki/View_from_the_Window_at_Le_Gras) was taken in 1827.
