"""
Flickr Group User Importer

Import images from a specific user within a Flickr group pool, filtered
by license.

Usage:
    uv run manage.py import flickr_group <group_nsid> --user <user_nsid> --username <display_name>

Example:
    uv run manage.py import flickr_group 12345678@N00 --user 98765432@N01 --username "Jane Doe" --dry-run
"""

import re
from time import sleep

import requests
from django.contrib.gis.geos import Point
from tqdm import tqdm

from images.models import Collection, Image, License, Source
from images.utils import R2Uploader

from .flickr import (
    BACKOFF_MULTIPLIER,
    MAX_BACKOFF_SECS,
    MAX_RETRIES,
    check_field_lengths,
    flickr_call_with_backoff,
    get_flickr_client,
    get_original_url,
    prompt_wait_secs,
)

SKIP_LICENSE_PROMPT = True

ALLOWED_LICENSES = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16}


def get_or_create_flickr_source():
    """Get or create the Flickr source."""
    source, created = Source.objects.get_or_create(
        name="Flickr",
        defaults={
            "url": "https://www.flickr.com/",
            "description": (
                "Flickr is an image and video hosting service with many "
                "institutional collections of historical photographs."
            ),
            "public": True,
        },
    )
    if created:
        print(f"Created source: {source.name}")
    else:
        print(f"Using existing source: {source.name}")
    return source


def get_or_create_user_collection(source, user_id, username):
    """Get or create a collection for a Flickr user."""
    user_url = f"https://www.flickr.com/photos/{user_id}/"

    collection, created = Collection.objects.get_or_create(
        source=source,
        name=username,
        defaults={
            "url": user_url,
            "description": f"Photos by {username} on Flickr.",
            "public": False,
        },
    )
    if created:
        print(f"Created PRIVATE collection: {collection.name}")
    else:
        print(f"Using existing collection: {collection.name}")
    return collection


def fetch_group_user_photos(flickr, group_id, user_id, wait_secs):
    """Paginate through a user's photos in a group pool, yielding each photo dict."""
    page = 1
    pages = None

    while True:
        resp = flickr_call_with_backoff(
            flickr.groups.pools.getPhotos,
            group_id=group_id,
            user_id=user_id,
            extras="license,description,owner_name,date_taken,date_taken_granularity,geo,url_o",
            per_page=500,
            page=page,
        )
        pool = resp["photos"]

        if pages is None:
            pages = pool["pages"]
            total = int(pool["total"])
            print(f"Found {total} photos by this user in the group")

        for photo in pool["photo"]:
            yield photo

        if page >= pages:
            break
        page += 1
        sleep(wait_secs)


def parse_flickr_date_taken(date_taken_str, granularity):
    """Convert Flickr's date_taken (YYYY-MM-DD HH:MM:SS) to EDTF (YYYY-MM-DD).

    Raises ValueError if granularity is not 0 (exact date).
    """
    if str(granularity) != "0":
        raise ValueError(
            f"Unsupported date_taken granularity: {granularity} "
            f"(only exact dates with granularity=0 are supported). "
            f"date_taken={date_taken_str!r}"
        )

    if not date_taken_str:
        return "", ""

    # date_taken format: "YYYY-MM-DD HH:MM:SS"
    date_part = date_taken_str.split(" ")[0]
    return date_taken_str, date_part


def get_license_by_flickr_id(flickr_id):
    """Look up a License by its Flickr ID. Returns None if not found."""
    try:
        return License.objects.get(flickr_id=flickr_id)
    except License.DoesNotExist:
        return None


def process_group_user(
    flickr, group_id, user_id, username, collection, options, wait_secs
):
    """Import photos from a specific user in a Flickr group pool."""
    dry_run = options.get("dry_run", False)
    max_images = options.get("max_images")
    skip = options.get("skip", 0)
    r2_uploader = None if dry_run else R2Uploader()

    imported = 0
    skipped = 0
    errors = 0
    license_skipped = 0

    photos = fetch_group_user_photos(flickr, group_id, user_id, wait_secs)

    for i, photo in enumerate(tqdm(photos, desc="Processing photos")):
        if i < skip:
            continue
        if max_images and imported >= max_images:
            break

        photo_id = photo["id"]
        license_id = int(photo.get("license", -1))

        # Filter by allowed licenses
        if license_id not in ALLOWED_LICENSES:
            license_skipped += 1
            continue

        # Look up the License model
        license_obj = get_license_by_flickr_id(license_id)
        if license_obj is None:
            tqdm.write(
                f"  ✗ No License in database with flickr_id={license_id} for photo {photo_id}"
            )
            errors += 1
            continue

        # Build the Flickr page URL (used for duplicate detection)
        original_url = f"https://www.flickr.com/photos/{user_id}/{photo_id}/"

        # Duplicate check on original_url
        if Image.objects.filter(original_url=original_url).exists():
            skipped += 1
            continue

        title = photo.get("title", "") or "Untitled"

        # Clean up the description
        raw_desc = photo.get("description", {}).get("_content", "")
        clean_desc = re.sub(r"<[^>]+>", "\n", raw_desc).strip()
        clean_desc = re.sub(r"&amp;", "&", clean_desc)
        clean_desc = re.sub(r"&lt;", "<", clean_desc)
        clean_desc = re.sub(r"&gt;", ">", clean_desc)
        clean_desc = re.sub(r"&quot;", '"', clean_desc)
        clean_desc = re.sub(r"\n{3,}", "\n\n", clean_desc)

        # Parse date
        date_taken = photo.get("datetaken", "")
        granularity = photo.get("datetakengranularity", "0")
        try:
            original_date, edtf_date = parse_flickr_date_taken(date_taken, granularity)
        except ValueError as e:
            tqdm.write(f"  ✗ Date error for {photo_id}: {e}")
            errors += 1
            continue

        # Build source_point from geo data if available
        source_point = None
        lat = photo.get("latitude")
        lon = photo.get("longitude")
        if lat and lon:
            lat_f, lon_f = float(lat), float(lon)
            if lat_f != 0 or lon_f != 0:
                source_point = Point(lon_f, lat_f, srid=4326)

        # Validate field lengths
        saveable = {
            "title": title,
            "creator": username,
            "ref": "",
            "original_date": original_date,
            "edtf_date": edtf_date,
        }
        saveable = check_field_lengths(photo_id, saveable)
        if saveable is None:
            tqdm.write(f"  ⏭ Skipped {photo_id} by user request")
            skipped += 1
            continue
        title = saveable["title"]
        original_date = saveable["original_date"]
        edtf_date = saveable["edtf_date"]

        if dry_run:
            tqdm.write(
                f"  [dry-run] {title}\n"
                f"    license={license_obj.name}  date={original_date}  edtf={edtf_date}\n"
                f"    creator={username}\n"
                f"    url={original_url}"
                f"{'  geo=' + str(source_point) if source_point else ''}"
            )
            imported += 1
            continue

        # Get the highest-resolution image URL
        sleep(wait_secs)
        try:
            image_url = get_original_url(flickr, photo_id)
        except Exception as e:
            tqdm.write(f"  ✗ Error getting sizes for {photo_id}: {e}")
            errors += 1
            continue

        if not image_url:
            tqdm.write(f"  ✗ No image URL found for {photo_id}")
            errors += 1
            continue

        # Upload to R2
        permalink = None
        backoff = wait_secs
        for attempt in range(MAX_RETRIES):
            try:
                permalink = r2_uploader.upload_url(image_url)
                break
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECS)
                    tqdm.write(
                        f"  ⏳ CDN rate limited (429) for {photo_id}, "
                        f"backing off {backoff:.0f}s (attempt {attempt + 1}/{MAX_RETRIES})..."
                    )
                    sleep(backoff)
                else:
                    tqdm.write(f"  ✗ Download error for {photo_id}: {e}")
                    errors += 1
                    break
            except Exception as e:
                tqdm.write(f"  ✗ Upload error for {photo_id}: {e}")
                errors += 1
                break
        else:
            tqdm.write(f"  ✗ Gave up on {photo_id} after {MAX_RETRIES} attempts")
            errors += 1

        if not permalink:
            continue

        # Create the Image record
        try:
            image = Image.objects.create(
                collection=collection,
                title=title,
                permalink=permalink,
                original_url=original_url,
                description=clean_desc,
                creator=username,
                original_date=original_date,
                edtf_date=edtf_date or None,
                license=license_obj,
                source_point=source_point,
            )
            tqdm.write(f"  ✓ #{image.id} {title}")
            imported += 1
        except Exception as e:
            tqdm.write(f"  ✗ DB error for {photo_id}: {e}")
            errors += 1

        sleep(wait_secs)

    return imported, skipped, errors, license_skipped


def add_arguments(parser):
    """Add flickr_group-specific arguments to the parser."""
    parser.add_argument(
        "group",
        type=str,
        help="Flickr group NSID (e.g. 12345678@N00)",
    )
    parser.add_argument(
        "--user",
        type=str,
        required=True,
        help="Flickr user NSID to import photos from",
    )
    parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="Display name for the user (used as collection name and creator)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Number of photos to skip from the start",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Maximum number of images to import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without downloading or creating records",
    )


def handle(options):
    """Run the Flickr group user import."""
    group_id = options["group"]
    user_id = options["user"]
    username = options["username"]

    print("\n=== Flickr Group User Import ===")
    print(f"Group: {group_id}")
    print(f"User: {user_id} ({username})")

    flickr = get_flickr_client()
    wait_secs = prompt_wait_secs()
    print(f"Wait between requests: {wait_secs}s")

    if options.get("dry_run"):
        print("Mode: DRY RUN")

    # Set up source and collection
    source = get_or_create_flickr_source()
    collection = get_or_create_user_collection(source, user_id, username)

    # Process photos
    imported, skipped, errors, license_skipped = process_group_user(
        flickr,
        group_id,
        user_id,
        username,
        collection,
        options,
        wait_secs,
    )

    # Summary
    print("\n=== Import Complete ===")
    action = "Would import" if options.get("dry_run") else "Imported"
    print(f"{action}: {imported} images")
    if skipped:
        print(f"Skipped (duplicate): {skipped}")
    if license_skipped:
        print(f"Skipped (license): {license_skipped}")
    if errors:
        print(f"Errors: {errors}")
