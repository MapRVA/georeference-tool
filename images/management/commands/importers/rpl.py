"""Import images from Richmond Public Library ContentDM.

Usage: uv run manage.py import rpl
"""

import re
from time import sleep

import requests
from django.utils.text import slugify
from tqdm import tqdm

from images.models import Collection, Image, Source
from images.utils import R2Uploader, R2UploaderError

POLITE_WAIT_SECS = 0.75  # Be nice to the API
MAX_RETRIES = 2  # Retry twice (3 total attempts)

# ContentDM API endpoints
BASE_API_URL = "https://rvalibrary.contentdm.oclc.org/digital/api"
BASE_VIEWER_URL = "https://rvalibrary.contentdm.oclc.org/digital/collection"
BASE_IMAGE_URL = "https://rvalibrary.contentdm.oclc.org/digital/download/collection"


def get_or_create_source():
    """Get or create the Richmond Public Library source"""
    source, created = Source.objects.get_or_create(
        name="Richmond Public Library",
        defaults={
            "url": "https://rvalibrary.contentdm.oclc.org/digital/",
            "description": "The Richmond Public Library's digital collections contain historical photographs, documents, and other materials related to Richmond, Virginia's history.",
            "public": True,
        },
    )
    if created:
        print(f"✓ Created source: {source.name}")
    else:
        print(f"✓ Using existing source: {source.name}")
    return source


def get_or_create_collection(source, collection_code):
    """Get or create a collection for the given ContentDM collection"""
    collection_info = f"{BASE_API_URL}/collections/{collection_code}"
    session = requests.Session()

    try:
        response = session.get(collection_info, timeout=30)
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as e:
        print(f"  ✗ Error fetching {collection_code}: {e}")

    name = data.get("name")
    collection_url = f"{BASE_VIEWER_URL}/{collection_code}"

    # Generate slug consistently with the model's save method
    slug = "memory-lab" if collection_code == "memorylab" else slugify(name[:50])

    collection, created = Collection.objects.get_or_create(
        source=source,
        name=name,
        slug=slug,
        defaults={
            "url": collection_url,
            "description": data.get("pageText", "")
            .replace("&amp;apos;", "'")
            .replace("&amp;lt;p&amp;gt;", "")
            .replace("&amp;lt;/p&amp;gt;", "")
            .replace("&#64;", "@"),
            "public": True,
        },
    )
    if created:
        print(f"  ✓ Created collection: {collection.name}")
    else:
        print(f"  ✓ Using existing collection: {collection.name}")
    return collection


def fetch_items(collection_code, start=1, max_items=None):
    """Fetch items from ContentDM API"""
    items = []
    page = 1
    per_page = 100
    session = requests.Session()

    with tqdm(desc="Fetching items", unit="page") as pbar:
        while True:
            url = f"{BASE_API_URL}/search/collection/{collection_code}/page/{page}/maxRecords/{per_page}"

            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
                data = response.json()

                if not data.get("items"):
                    break

                items.extend(data["items"])

                if max_items and len(items) >= max_items:
                    items = items[:max_items]
                    break

                if len(data["items"]) < per_page:
                    break

                start += per_page
                page += 1
                pbar.update(1)
                sleep(POLITE_WAIT_SECS)

            except requests.RequestException as e:
                print(f"  ✗ Error fetching page {page}: {e}")
                break

    return items


def process_items(
    collection, collection_code, items, dry_run=False, r2_uploader=None, debug=None
):
    """Process and import items from ContentDM"""
    imported_count = 0

    with tqdm(total=len(items), desc="Processing items") as pbar:
        for item in items:
            # Get required fields
            contentdm_id = item.get("itemId")
            if not contentdm_id:
                print("    ✗ No itemId found, skipping")
                pbar.update(1)
                continue

            # Build URLs
            original_url = f"{BASE_VIEWER_URL}/{collection_code}/id/{contentdm_id}"
            image_url = (
                f"{BASE_IMAGE_URL}/{collection_code}/id/{contentdm_id}/size/full"
            )
            item_info_url = f"{BASE_API_URL}/collections/{collection_code}/items/{contentdm_id}/false"

            # Poll image metadata with retries
            session = requests.Session()
            item_info = None

            for attempt in range(MAX_RETRIES + 1):
                try:
                    response = session.get(item_info_url, timeout=30)
                    response.raise_for_status()
                    item_info = response.json().get("fields", {})
                    break  # Success, exit retry loop

                except requests.RequestException as e:
                    if attempt < MAX_RETRIES:
                        print(
                            f"    ⚠ Error fetching metadata for {contentdm_id} (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}"
                        )
                        print("    → Retrying...")
                        sleep(POLITE_WAIT_SECS * 2)  # Wait a bit longer before retry
                    else:
                        print(
                            f"    ✗ Error fetching metadata for {contentdm_id} after {MAX_RETRIES + 1} attempts: {e}"
                        )
                        pbar.update(1)
                        continue  # Skip to next item

            if item_info is None:
                continue  # Skip this item if we couldn't get metadata

            image_data = dict(
                zip(
                    [item["label"] for item in item_info],
                    [item["value"] for item in item_info],
                )
            )

            # Check if image already exists by ref
            if Image.objects.filter(ref=image_data["Identifier"]).exists():
                print(
                    "    → Item {} already exists, skipping".format(
                        image_data["Identifier"]
                    )
                )
                pbar.update(1)
                continue

            # Upload to R2 if not dry run (with retries for downloading from RPL)
            if not dry_run and r2_uploader:
                permalink = None
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        permalink = r2_uploader.upload_url(image_url)
                        break  # Success, exit retry loop

                    except R2UploaderError as e:
                        if attempt < MAX_RETRIES:
                            print(
                                f"    ⚠ Download failed for {contentdm_id} (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}"
                            )
                            print("    → Retrying...")
                            sleep(
                                POLITE_WAIT_SECS * 2
                            )  # Wait a bit longer before retry
                        else:
                            print(
                                f"    ✗ Download failed for {contentdm_id} after {MAX_RETRIES + 1} attempts: {e}"
                            )
                            pbar.update(1)
                            continue  # Skip to next item

                if permalink is None:
                    continue  # Skip this item if we couldn't download the image
            else:
                mock_key = r2_uploader.generate_key_from_url(image_url)
                permalink = r2_uploader.get_public_url(mock_key)

            image_description = image_data["Description"]

            if "Subject" in image_data.keys():
                image_description += "\n\n{}".format(image_data["Subject"])

            if "Provenance" in image_data.keys():
                image_description += "\n\n{}".format(image_data["Provenance"])

            # Parse dates
            date_str = image_data.get("Date", "")

            if date_str != "":
                # Date range (Sequential years separated by ";" and maybe spaces)
                year_range_match = re.search(r";", date_str)
                if year_range_match:
                    year_range = re.split(r";\s|;", date_str)
                    image_data["etdf_date"] = year_range[0] + "/" + year_range[-1]
                else:
                    image_data["etdf_date"] = date_str

            # Create image data to export
            image_data = {
                "collection": collection,
                "title": image_data.get("Title", "Untitled"),
                "permalink": permalink,
                "ref": image_data["Identifier"],
                "original_url": original_url,
                "description": image_description,
                "creator": image_data.get("Creator", ""),
                "original_date": image_data.get("Date"),
                "edtf_date": image_data.get("etdf_date"),
                "license_title": "Non-commercial Use Only",
            }

            if not dry_run:
                try:
                    image = Image.objects.create(**image_data)
                    print(f"    ✓ Created image ID: {image.id}")
                    imported_count += 1
                except Exception as e:
                    print(f"    ✗ Error creating image: {e}")
            else:
                print(f"    → Would create image: {image_data['title']} (dry run)")
                imported_count += 1

            pbar.update(1)
            sleep(POLITE_WAIT_SECS)

    if debug == "image":
        return [imported_count, image_data]
    else:
        return [imported_count]


def add_arguments(parser):
    """Add rpl-specific arguments to the parser."""
    parser.add_argument(
        "--collection-code",
        default="RPLTHC",
        help="ContentDM collection code (default: RPLTHC)",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        help="Maximum number of images to import (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without actually importing",
    )
    parser.add_argument(
        "--debug",
        default=None,
        help='Print metadata ("meta") or image data ("image") for debugging',
    )


def handle(options):
    """Run the Richmond Public Library import."""
    collection_code = options["collection_code"]
    max_images = options["max_images"]
    dry_run = options["dry_run"]
    debug = options["debug"]

    print(f"\n=== Importing Collection: {collection_code} ===")

    # Initialize R2 uploader
    r2_uploader = R2Uploader()

    # Get or create source and collection
    source = get_or_create_source()
    coll = get_or_create_collection(source, collection_code)

    # Fetch items from API
    items = fetch_items(collection_code, max_items=max_images)
    if not items:
        print("✗ No items found")
        return

    print(f"\nFound {len(items)} items to process")

    # Process items
    imported_count = process_items(
        coll, collection_code, items, dry_run, r2_uploader, debug
    )

    if debug == "meta":
        print(f"\n=== Debug: {debug} ===")
        print(f"{items}")
    if debug == "image":
        print(f"\n=== Debug: {debug} ===")
        print(f"{imported_count[1]}")

    # Print summary
    print("\n=== Import Complete ===")
    print(f"{'Would import' if dry_run else 'Imported'}: {imported_count[0]} images")
    print(f"Collection: {collection_code}")
