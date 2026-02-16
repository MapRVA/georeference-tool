"""
Flickr Album Importer

Import images from Flickr photosets (albums).

Supports two modes:
  1. "album" mode (implemented): Import all photos from an album owned by a
     single known user. Metadata is parsed from photo descriptions using
     regex patterns (Title, Date, Identifier, etc.).

  2. "curated" mode (placeholder): Import from albums with mixed contributors
     and licenses. Requires filtering by allowed user IDs and license types.

Usage:
    uv run manage.py import flickr <album_url_or_id> [options]

Example:
    uv run manage.py import flickr https://www.flickr.com/photos/library_of_virginia/albums/72157607704129043/
    uv run manage.py import flickr 72157607704129043 --dry-run --max-images 5
"""

import re
from time import sleep

import flickrapi
from django.conf import settings
from flickrapi.exceptions import FlickrError
from tqdm import tqdm

from images.models import Collection, Image, Source
from images.utils import R2Uploader

DEFAULT_POLITE_WAIT_SECS = 1.0
BACKOFF_MULTIPLIER = 2
MAX_BACKOFF_SECS = 120
MAX_RETRIES = 5

# Flickr license IDs that represent public domain / no known restrictions
# See https://www.flickr.com/services/api/flickr.photos.licenses.getInfo.html
PUBLIC_DOMAIN_LICENSES = {
    7,  # No known copyright restrictions
    9,  # Public Domain Dedication (CC0)
    10,  # Public Domain Mark
}


def prompt_wait_secs():
    """Ask the user to configure the polite wait time between API requests."""
    choice = input(
        f"\nSeconds to wait between API requests [{DEFAULT_POLITE_WAIT_SECS}]: "
    ).strip()
    if not choice:
        return DEFAULT_POLITE_WAIT_SECS
    try:
        value = float(choice)
        if value < 0:
            print("Wait time cannot be negative, using default.")
            return DEFAULT_POLITE_WAIT_SECS
        return value
    except ValueError:
        print("Invalid number, using default.")
        return DEFAULT_POLITE_WAIT_SECS


def flickr_call_with_backoff(func, *args, **kwargs):
    """Call a Flickr API method with exponential backoff on 429 errors."""
    backoff = MAX_BACKOFF_SECS / (BACKOFF_MULTIPLIER ** (MAX_RETRIES - 1))
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except FlickrError as e:
            if "429" in str(e) and attempt < MAX_RETRIES:
                wait = min(backoff, MAX_BACKOFF_SECS)
                tqdm.write(f"  ⏳ Rate limited (429), backing off {wait:.0f}s...")
                sleep(wait)
                backoff *= BACKOFF_MULTIPLIER
            else:
                raise


def extract_album_id(album_input):
    """Extract a Flickr album (photoset) ID from a URL or raw ID string."""
    match = re.search(r"albums/(\d+)", album_input)
    if match:
        return match.group(1)
    if album_input.isdigit():
        return album_input
    raise ValueError(
        f"Could not extract album ID from: {album_input}\n"
        f"Provide a Flickr album URL or numeric album ID."
    )


def get_flickr_client():
    """Create a FlickrAPI client using Django settings."""
    api_key = getattr(settings, "FLICKR_API_KEY", None)
    api_secret = getattr(settings, "FLICKR_API_SECRET", None)
    if not api_key:
        raise RuntimeError(
            "FLICKR_API_KEY is not set in Django settings. "
            "Add FLICKR_API_KEY (and optionally FLICKR_API_SECRET) to your settings."
        )
    return flickrapi.FlickrAPI(
        api_key, api_secret or "", format="parsed-json", token_cache_location="/tmp"
    )


def parse_description_fields(description):
    """Parse structured metadata fields out of a Flickr photo description.

    Expects a description with labeled fields like:
        Title: Some title
        Creator: Some creator
        Date: 1961 July 21
        Identifier: Rice Collection 3365A

    Returns a dict of parsed fields (lowercase keys).
    """
    fields = {}
    # Match lines like "Key: Value" – value runs to the next key or end of string
    pattern = re.compile(
        r"^\s*(?P<key>Title|Creator|Date|Identifier|Format|Rights Info|Repository)"
        r"\s*:\s*(?P<value>.+?)(?=\n\s*(?:Title|Creator|Date|Identifier|Format|Rights Info|Repository)\s*:|$)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(description):
        key = match.group("key").strip().lower().replace(" ", "_")
        value = match.group("value").strip()
        # Collapse internal whitespace (descriptions often have runs of spaces/newlines)
        value = re.sub(r"\s+", " ", value)
        fields[key] = value
    return fields


def parse_flickr_date(date_str):
    """Parse date strings from LVA Flickr descriptions into EDTF.

    Handles formats like:
        1961 July 21  -> 1961-07-21
        1955 March    -> 1955-03
        1920          -> 1920
        ca. 1920      -> 1920~
        undated       -> ""
    """
    if not date_str:
        return ""

    date_str = date_str.strip()

    if date_str.lower() in ("undated", "n.d.", "no date"):
        return ""

    # "ca." / "circa" prefix
    circa = False
    cleaned = date_str
    ca_match = re.match(r"^(?:ca\.?|circa)\s+(.+)$", cleaned, re.IGNORECASE)
    if ca_match:
        circa = True
        cleaned = ca_match.group(1)

    suffix = "~" if circa else ""

    month_map = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    # YYYY Month DD
    m = re.match(r"^(\d{4})\s+(\w+)\s+(\d{1,2})$", cleaned)
    if m:
        year, month_name, day = m.group(1), m.group(2), int(m.group(3))
        month = month_map.get(month_name.lower())
        if month:
            return f"{year}-{month:02d}-{day:02d}{suffix}"

    # YYYY Month
    m = re.match(r"^(\d{4})\s+(\w+)$", cleaned)
    if m:
        year, month_name = m.group(1), m.group(2)
        month = month_map.get(month_name.lower())
        if month:
            return f"{year}-{month:02d}{suffix}"

    # Plain year
    m = re.match(r"^(\d{4})$", cleaned)
    if m:
        return f"{cleaned}{suffix}"

    # Year range YYYY-YYYY
    m = re.match(r"^(\d{4})\s*[-–]\s*(\d{4})$", cleaned)
    if m:
        return f"{m.group(1)}/{m.group(2)}{suffix}"

    # Fall back: return the original string as original_date only
    return ""


def select_source():
    """Prompt the user to select an existing source or create the default Flickr source."""
    sources = list(Source.objects.order_by("name"))

    print("\nSelect a source for this collection:")
    print("  [0] Create new 'Flickr' source (default)")
    for i, source in enumerate(sources, start=1):
        print(f"  [{i}] {source.name}")

    choice = input("\nSource [0]: ").strip()

    if choice == "" or choice == "0":
        source, created = Source.objects.get_or_create(
            name="Flickr",
            defaults={
                "url": "https://www.flickr.com/",
                "description": "Flickr is an image and video hosting service with many institutional collections of historical photographs.",
                "public": True,
            },
        )
        if created:
            print(f"Created source: {source.name}")
        else:
            print(f"Using existing source: {source.name}")
        return source

    try:
        idx = int(choice)
        if 1 <= idx <= len(sources):
            source = sources[idx - 1]
            print(f"Using existing source: {source.name}")
            return source
    except ValueError:
        pass

    print("Invalid choice, using default Flickr source.")
    return select_source()


def get_or_create_collection(source, album_info):
    """Get or create a collection for this Flickr album."""
    album_title = album_info["title"]
    album_url = (
        f"https://www.flickr.com/photos/{album_info['owner']}/albums/{album_info['id']}"
    )

    collection, created = Collection.objects.get_or_create(
        source=source,
        name=album_title,
        defaults={
            "url": album_url,
            "description": album_info.get("description", ""),
            "public": False,
        },
    )
    if created:
        print(f"Created PRIVATE collection: {collection.name}")
    else:
        print(f"Using existing collection: {collection.name}")
    return collection


def get_original_url(flickr_json, photo_id):
    """Get the URL of the largest available size for a photo."""
    sizes = flickr_call_with_backoff(flickr_json.photos.getSizes, photo_id=photo_id)
    size_list = sizes["sizes"]["size"]

    # Prefer Original, then Large, then whatever is biggest
    preferred = ["Original", "Large 2048", "Large 1600", "Large"]
    for pref in preferred:
        for s in size_list:
            if s["label"] == pref:
                return s["source"]

    # Fall back to the last (usually largest) size
    return size_list[-1]["source"] if size_list else None


def fetch_album_photos(flickr, album_id, total, wait_secs):
    """Paginate through all photos in an album, yielding each photo dict.

    Handles pagination via flickr.photosets.getPhotos with parsed-json format,
    avoiding the broken walk_set (uses getchildren(), removed in Python 3.9).
    """
    per_page = 500
    pages = (total + per_page - 1) // per_page

    for page in range(1, pages + 1):
        resp = flickr_call_with_backoff(
            flickr.photosets.getPhotos,
            photoset_id=album_id,
            extras="description,license,owner_name,date_taken,url_o",
            per_page=per_page,
            page=page,
        )
        for photo in resp["photoset"]["photo"]:
            yield photo
        if page < pages:
            sleep(wait_secs)


def process_album(flickr, album_id, collection, owner, total, options, wait_secs):
    """Enumerate photos in an album and import them.

    Mode 1 ("album"): parse metadata from descriptions, import everything.
    """
    dry_run = options.get("dry_run", False)
    max_images = options.get("max_images")
    r2_uploader = None if dry_run else R2Uploader()

    imported = 0
    skipped = 0
    errors = 0

    photos = fetch_album_photos(flickr, album_id, total, wait_secs)

    for photo in tqdm(photos, total=total, desc="Processing photos"):
        if max_images and imported >= max_images:
            break

        photo_id = photo["id"]
        title_attr = photo.get("title", "")

        # Get the full photo description
        raw_desc = photo.get("description", {}).get("_content", "")

        # Strip HTML tags that Flickr sometimes wraps descriptions in
        clean_desc = re.sub(r"<[^>]+>", "\n", raw_desc).strip()
        clean_desc = re.sub(r"&amp;", "&", clean_desc)
        clean_desc = re.sub(r"&lt;", "<", clean_desc)
        clean_desc = re.sub(r"&gt;", ">", clean_desc)
        clean_desc = re.sub(r"&quot;", '"', clean_desc)
        clean_desc = re.sub(r"\n{3,}", "\n\n", clean_desc)

        # Parse structured fields from description
        fields = parse_description_fields(clean_desc)

        title = fields.get("title", title_attr) or "Untitled"
        creator = fields.get("creator", "")
        date_str = fields.get("date", "")
        ref = fields.get("identifier", "")
        edtf_date = parse_flickr_date(date_str)

        # Duplicate check
        if ref and Image.objects.filter(ref=ref).exists():
            skipped += 1
            continue

        # Build the Flickr page URL for this photo
        original_url = f"https://www.flickr.com/photos/{owner}/{photo_id}/"

        if dry_run:
            tqdm.write(
                f"  [dry-run] {title}\n"
                f"    ref={ref}  date={date_str}  edtf={edtf_date}\n"
                f"    creator={creator}\n"
                f"    url={original_url}"
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

        # Upload to R2 (with backoff on 429s from Flickr CDN)
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
                ref=ref,
                original_url=original_url,
                description=clean_desc,
                creator=creator,
                original_date=date_str,
                edtf_date=edtf_date or None,
            )
            tqdm.write(f"  ✓ #{image.id} {title}")
            imported += 1
        except Exception as e:
            tqdm.write(f"  ✗ DB error for {photo_id}: {e}")
            errors += 1

        sleep(wait_secs)

    return imported, skipped, errors


def add_arguments(parser):
    """Add flickr-specific arguments to the parser."""
    parser.add_argument(
        "album",
        type=str,
        help="Flickr album URL or numeric album ID",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Maximum number of images to import (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without downloading or creating records",
    )


def handle(options):
    """Run the Flickr album import."""
    album_input = options["album"]
    album_id = extract_album_id(album_input)

    print("\n=== Flickr Album Import ===")
    print(f"Album ID: {album_id}")

    flickr = get_flickr_client()
    wait_secs = prompt_wait_secs()
    print(f"Wait between requests: {wait_secs}s")

    # Fetch album metadata
    album_info_resp = flickr_call_with_backoff(
        flickr.photosets.getInfo, photoset_id=album_id
    )
    photoset = album_info_resp["photoset"]
    album_info = {
        "id": album_id,
        "title": photoset["title"]["_content"],
        "description": photoset["description"]["_content"],
        "owner": photoset["owner"],
        "count": photoset["count_photos"],
    }

    print(f"Album: {album_info['title']}")
    print(f"Owner: {album_info['owner']}")
    print(f"Photos: {album_info['count']}")

    if options.get("dry_run"):
        print("Mode: DRY RUN")

    # Set up source and collection
    source = select_source()
    collection = get_or_create_collection(source, album_info)

    # Process photos
    imported, skipped, errors = process_album(
        flickr,
        album_id,
        collection,
        album_info["owner"],
        int(album_info["count"]),
        options,
        wait_secs,
    )

    # Summary
    print("\n=== Import Complete ===")
    action = "Would import" if options.get("dry_run") else "Imported"
    print(f"{action}: {imported} images")
    if skipped:
        print(f"Skipped (duplicate): {skipped}")
    if errors:
        print(f"Errors: {errors}")
