import os
import sys
from time import sleep

import click
import requests
import re
from tqdm import tqdm

## SETUP
# Add the Django project to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(script_dir, "..", "..")
sys.path.insert(0, project_root)

# Change to project directory for Django
os.chdir(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "georeference_tool.settings")

import django

django.setup()

from images.models import Collection, Image, Source

# Import R2 uploader from the same directory
try:
    from r2_uploader import R2Uploader, R2UploaderError
except ImportError:
    # since we aren't inside a package, relative imports might not work
    import os
    import sys

    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    from r2_uploader import R2Uploader

POLITE_WAIT_SECS = 0.75  # Be nice to the API

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
        click.echo(f"✓ Created source: {source.name}")
    else:
        click.echo(f"✓ Using existing source: {source.name}")
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
        click.echo(f"  ✗ Error fetching {collection_code}: {e}", err=True)

    name = data.get("name")
    collection_url = f"{BASE_VIEWER_URL}/{collection_code}"

    collection, created = Collection.objects.get_or_create(
        source=source,
        name=name,
        slug="memory-lab" if collection_code == "memorylab" else None,
        description=data.get("pageText")
        .replace("&amp;apos;", "'")
        .replace("&amp;lt;p&amp;gt;", "")
        .replace("&amp;lt;/p&amp;gt;", "")
        .replace("&#64;", "@"),
        defaults={
            "url": collection_url,
            "public": True,
        },
    )
    if created:
        click.echo(f"  ✓ Created collection: {collection.name}")
    else:
        click.echo(f"  ✓ Using existing collection: {collection.name}")
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
                click.echo(f"  ✗ Error fetching page {page}: {e}", err=True)
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
                click.echo("    ✗ No itemId found, skipping", err=True)
                pbar.update(1)
                continue

            # Build URLs
            original_url = f"{BASE_VIEWER_URL}/{collection_code}/id/{contentdm_id}"
            image_url = f"{BASE_IMAGE_URL}/{collection_code}/id/{contentdm_id}/size/full"
            item_info_url = f"{BASE_API_URL}/collections/{collection_code}/items/{contentdm_id}/false"

            # Upload to R2 if not dry run
            if not dry_run and r2_uploader:
                try:
                    permalink = r2_uploader.upload_url(image_url)
                except R2UploaderError as e:
                    click.echo(
                        f"    ✗ R2 upload failed for {contentdm_id}: {e}", err=True
                    )
                    pbar.update(1)
                    continue
            else:
                mock_key = r2_uploader.generate_key_from_url(image_url)
                permalink = r2_uploader.get_public_url(mock_key)

            # Poll image metadata
            session = requests.Session()

            try:
                response = session.get(item_info_url, timeout=30)
                response.raise_for_status()
                item_info = response.json().get("fields", {})

            except requests.RequestException as e:
                click.echo(f"  ✗ Error fetching {collection_code}: {e}", err=True)

            image_data = dict(
                zip(
                    [item["label"] for item in item_info],
                    [item["value"] for item in item_info]
                )
            )

            # Check if image already exists by ref
            if Image.objects.filter(ref=image_data["Identifier"]).exists():
                click.echo("    → Item {} already exists, skipping".format(image_data["Identifier"]))
                pbar.update(1)
                continue

            image_description = "{}\n\nSubject: {}\n\nProvenance: {}".format(image_data["Description"], image_data["Subject"], image_data["Provenance"])

            # Parse dates
            date_str = image_data.get("Date", "")

            if date_str != "":
                # Date range (Sequential years separated by ";" and maybe spaces)
                year_range_match = re.search(r";", date_str)
                if year_range_match:
                    year_range = re.split(r";\s|;", date_str)
                    image_data["etdf_date"] = (
                        year_range[0] + "/" + year_range[-1]
                    )
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
                    click.echo(f"    ✓ Created image ID: {image.id}")
                    imported_count += 1
                except Exception as e:
                    click.echo(f"    ✗ Error creating image: {e}", err=True)
            else:
                click.echo(f"    → Would create image: {image_data['title']} (dry run)")
                imported_count += 1

            pbar.update(1)
            sleep(POLITE_WAIT_SECS)

    if debug == "image":
        return [imported_count, image_data]
    else:
        return [imported_count]


@click.command()
@click.option(
    "--collection-code",
    default="RPLTHC",
    help="ContentDM collection code (default: RPLTHC)",
)
@click.option(
    "--max-images",
    type=int,
    help="Maximum number of images to import (for testing)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be imported without actually importing",
)
@click.option(
    "--debug",
    default=None,
    help='Print metadata ("meta") or image data ("image") for debugging',
)
def main(collection_code, max_images, dry_run, debug):
    """Import images from Richmond Public Library ContentDM"""
    click.echo(f"\n=== Importing Collection: {collection_code} ===")

    # Initialize R2 uploader
    r2_uploader = R2Uploader()

    # Get or create source and collection
    source = get_or_create_source()
    coll = get_or_create_collection(source, collection_code)

    # Fetch items from API
    items = fetch_items(collection_code, max_items=max_images)
    if not items:
        click.echo("✗ No items found")
        return

    click.echo(f"\nFound {len(items)} items to process")

    # Process items
    imported_count = process_items(
        coll, collection_code, items, dry_run, r2_uploader, debug
    )

    if debug == "meta":
        click.echo(f"\n=== Debug: {debug} ===")
        click.echo(f"{items}")
    if debug == "image":
        click.echo(f"\n=== Debug: {debug} ===")
        click.echo(f"{imported_count[1]}")

    # Print summary
    click.echo("\n=== Import Complete ===")
    click.echo(
        f"{'Would import' if dry_run else 'Imported'}: {imported_count[0]} images"
    )
    click.echo(f"Collection: {collection_code}")


if __name__ == "__main__":
    main()
