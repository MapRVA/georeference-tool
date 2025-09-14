#!/usr/bin/env python3
"""
Library of Congress Collection Scraper

New collections are PRIVATE, must be made public using admin interface.

Usage:
    uv run scripts/importers/library_of_congress.py

The script will interactively prompt for collection details.
"""

import os
import sys
import re
import requests
from time import sleep
from tqdm import tqdm
import click
from urllib.parse import quote

# Add the Django project to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(script_dir, "..", "..")
sys.path.insert(0, project_root)

# Change to project directory for Django
os.chdir(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "georeference_tool.settings")

import django

django.setup()

from images.models import Source, Collection, Image

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

POLITE_WAIT_SECS = 3.0  # 3 seconds as requested for LoC rate limiting


def create_source_if_not_exist():
    """Get or create Library of Congress source"""
    source, created = Source.objects.get_or_create(
        name="Library of Congress",
        defaults={
            "url": "https://www.loc.gov/",
            "description": "The Library of Congress is the research library that officially serves the United States Congress and is the de facto national library of the United States. It is the oldest federal cultural institution in the country.",
            "public": True,
        },
    )
    if created:
        print(f"Created source: {source.name}")
    else:
        print(f"Using existing source: {source.name}")
    return source


def get_collection_info():
    """Interactive prompt to get collection information from user"""
    print("\n=== Library of Congress Collection Import ===")
    print("Please provide the following collection information:")

    collection_slug = click.prompt(
        "Collection URL slug (e.g., 'detroit-publishing-company', 'sanborn-maps')",
        type=str,
    )

    # Check if a collection with this slug already exists in our database
    source = Source.objects.filter(name="Library of Congress").first()
    if source:
        # Look for existing collection that would have the same final name
        existing_collections = Collection.objects.filter(
            source=source,
        )

        # Find collection that likely matches this slug
        matching_collection = None
        for collection in existing_collections:
            if collection.slug == collection_slug:
                matching_collection = collection
                break

        if matching_collection:
            print(f"\n⚠️  Found existing collection that may match this slug:")
            print(f"  Name: {matching_collection.name}")
            print(f"  URL: {matching_collection.url}")
            print(f"  Description: {matching_collection.description}")
            print(f"  Public: {'Yes' if matching_collection.public else 'No'}")
            print(f"  Images: {matching_collection.images.count()}")

            if click.confirm(f"\nUse this existing collection?"):
                return {
                    "slug": collection_slug,
                    "name": matching_collection.name,
                    "description": matching_collection.description,
                    "existing_collection": matching_collection,
                }

    collection_name = click.prompt(
        "Collection display name (e.g., 'Detroit Publishing Company')", type=str
    )

    collection_description = click.prompt(
        "Collection description",
        type=str,
        default=f"Images from the {collection_name} collection at the Library of Congress, filtered for Richmond, Virginia.",
    )

    return {
        "slug": collection_slug,
        "name": collection_name,
        "description": collection_description,
    }


def create_collection_if_not_exist(source, collection_info):
    """Get or create a collection based on collection info"""
    # Check if we already have an existing collection from the info gathering
    if "existing_collection" in collection_info:
        print(
            f"  ✓ Using existing collection: {collection_info['existing_collection'].name}"
        )
        return collection_info["existing_collection"]

    collection_name = collection_info["name"]
    collection_url = f"https://www.loc.gov/collections/{collection_info['slug']}/?fa=location:virginia%7Clocation:richmond"

    # Check if collection already exists (shouldn't happen given our earlier check, but just in case)
    existing_collection = Collection.objects.filter(
        source=source, name=collection_name
    ).first()
    if existing_collection:
        print(f"  ✓ Using existing collection: {existing_collection.name}")
        return existing_collection

    # Show collection details to user for confirmation
    print(f"\n  Collection Details:")
    print(f"  Name: {collection_name}")
    print(f"  Source: {source.name}")
    print(f"  URL: {collection_url}")
    print(f"  Description: {collection_info['description']}")

    if click.confirm("\n  Create this collection?"):
        collection = Collection.objects.create(
            source=source,
            name=collection_name,
            url=collection_url,
            description=collection_info["description"],
            public=False,
        )
        print(f"Created PRIVATE collection: {collection.name}")
        return collection
    else:
        return None


def fetch_loc_results(collection_slug, start_page=1, items_per_page=150):
    """Fetch results from Library of Congress API"""
    base_url = f"https://www.loc.gov/collections/{collection_slug}/"
    params = {
        "fa": "location:virginia|location:richmond",  # Hard-coded search params
        "fo": "json",
        "c": items_per_page,
        "sp": start_page,
    }

    response = requests.get(base_url, params=params)
    response.raise_for_status()

    # Debug: print response details if it's not JSON
    try:
        json_data = response.json()
        return json_data
    except requests.exceptions.JSONDecodeError:
        print(f"Error: Response is not JSON. Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type', 'Not specified')}")
        print(f"URL: {response.url}")
        print(f"Response text (first 500 chars): {response.text[:500]}")
        raise


def extract_image_data(result_item):
    """Extract relevant data from a LoC result item"""
    item_data = result_item.get("item", {})

    # Get title and clean up brackets if entire title is wrapped
    title = result_item.get("title", "Untitled")
    if title.startswith("[") and title.endswith("]"):
        title = title[1:-1].strip()

    # Build the record dictionary
    record = {
        "id": result_item.get("id", ""),
        "title": title,
        "original_url": result_item.get("url", ""),
        "ref": item_data.get("control_number", ""),
        "description": "",
        "creator": "",
        "original_date": "",
        "edtf_date": "",
        "image_urls": result_item.get("image_url", []),
        "resources": result_item.get("resources", []),
    }

    # Extract description from various fields
    descriptions = []
    if result_item.get("description"):
        descriptions.extend(result_item["description"])

    # Add subject information
    subjects = result_item.get("subject", [])
    if subjects:
        descriptions.append("Subjects: " + ", ".join(subjects))

    # Add location information
    locations = result_item.get("location", [])
    if locations:
        descriptions.append("Locations: " + ", ".join(locations))

    # Add notes from item data
    notes = item_data.get("notes", [])
    if notes:
        descriptions.append("")  # Add blank line before notes
        descriptions.append("Notes:")
        descriptions.extend(notes)

    record["description"] = "\n".join(descriptions)

    # Extract creator information
    contributors = item_data.get("contributors", [])
    if contributors:
        record["creator"] = contributors[0]  # Take first contributor
    elif result_item.get("contributor"):
        record["creator"] = ", ".join(result_item["contributor"])

    # Extract and process date - use item.date as primary source
    if item_data.get("date"):
        record["original_date"] = item_data["date"]
        record["edtf_date"] = parse_loc_date(item_data["date"])
    elif result_item.get("date"):
        record["original_date"] = result_item["date"]
        record["edtf_date"] = parse_loc_date(result_item["date"])

    if record["original_date"].startswith("[") and record["original_date"].endswith(
        "]"
    ):
        record["original_date"] = record["original_date"][1:-1].strip()

    return record


def parse_loc_date(date_str):
    """Parse Library of Congress date formats to EDTF"""
    if not date_str:
        return ""

    date_str = date_str.strip()

    # Remove square brackets if present
    if date_str.startswith("[") and date_str.endswith("]"):
        date_str = date_str[1:-1].strip()

    # Handle complex circa patterns with embedded brackets and question marks
    # Examples: "c[1901?]", "c1901?", etc.
    complex_circa_match = re.match(r"^c\[?(\d{4})\??\.?\]?$", date_str)
    if complex_circa_match:
        return complex_circa_match.group(1) + "~"

    # Handle "ca." or "circa" followed by year
    ca_match = re.match(r"^(?:ca\.|circa)\s+(\d{4})$", date_str, re.IGNORECASE)
    if ca_match:
        return ca_match.group(1) + "~"

    # Handle "c1905" or "c1905." format (circa dates with optional period)
    circa_match = re.match(r"^c(\d{4})\.?$", date_str)
    if circa_match:
        return circa_match.group(1) + "~"

    # Handle "between YYYY and YYYY" format
    between_match = re.match(r"^between (\d{4}) and (\d{4})$", date_str, re.IGNORECASE)
    if between_match:
        return between_match.group(1) + "/" + between_match.group(2)

    # Handle "between YYYY and YYYY" format
    between_match = re.match(
        r"^c\[?between (\d{4}) and (\d{4})\]?$", date_str, re.IGNORECASE
    )
    if between_match:
        return between_match.group(1) + "/" + between_match.group(2) + "~"

    # Handle simple year "1905"
    year_match = re.match(r"^(\d{4})$", date_str)
    if year_match:
        return year_match.group(1)

    # # Handle year ranges "1905-1910"
    # range_match = re.match(r"^(\d{4})-(\d{4})$", date_str)
    # if range_match:
    #     return range_match.group(1) + "/" + range_match.group(2)

    # # Handle "1905-01-01" ISO format
    # iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
    # if iso_match:
    #     return date_str

    # If we can't parse it, return the original
    return date_str


def get_highest_quality_image_url(record):
    """Get the highest quality image URL from the record"""
    best_url = None
    best_quality_score = 0

    # First, try resources - these often contain the highest quality images
    resources = record.get("resources", [])
    for resource in resources:
        url = resource.get("url", "")
        if url and "resource" in url:
            # Resources are typically the highest quality, give them high priority
            quality_score = 1000
            if quality_score > best_quality_score:
                best_quality_score = quality_score
                best_url = url

    # Then check image_urls for specific quality indicators
    image_urls = record.get("image_urls", [])
    for url in image_urls:
        if not url:
            continue

        quality_score = 0

        # Look for resolution indicators in the URL fragment
        if "#h=" in url and "&w=" in url:
            try:
                height_str = url.split("#h=")[1].split("&")[0]
                width_str = url.split("&w=")[1].split("&")[
                    0
                ]  # Handle additional params
                height = int(height_str)
                width = int(width_str)
                quality_score = height * width  # Total pixels as quality metric
            except (ValueError, IndexError):
                pass

        # Look for quality indicators in the filename
        url_lower = url.lower()
        if any(indicator in url_lower for indicator in ["_150px", "t.gif"]):
            # These are typically thumbnails - lower quality
            quality_score = max(quality_score, 1)
        elif "r.jpg" in url_lower:
            # Medium resolution
            quality_score = max(quality_score, 100)
        elif "v.jpg" in url_lower:
            # Often high resolution
            quality_score = max(quality_score, 500)
        # elif '.tif' in url_lower or 'master' in url_lower:
        #     # Typically highest quality
        #     quality_score = max(quality_score, 2000)

        if quality_score > best_quality_score:
            best_quality_score = quality_score
            best_url = url.split("#")[0]  # Remove fragment for clean URL

    return best_url


@click.command()
@click.option(
    "--max-items", default=None, type=int, help="Maximum number of items to process"
)
def main(max_items):
    """Scrape images from Library of Congress collections for Richmond, Virginia."""

    source = create_source_if_not_exist()
    collection_info = get_collection_info()
    collection = create_collection_if_not_exist(source, collection_info)

    if not collection:
        print("Collection creation cancelled.")
        return

    r2_uploader = R2Uploader()

    # First, get the total count
    print(f"\nFetching results for collection: {collection_info['slug']}")
    initial_results = fetch_loc_results(
        collection_info["slug"], start_page=1, items_per_page=150
    )

    total_results = initial_results.get("pagination", {}).get("of", 0)
    print(f"Found {total_results} total results")

    if max_items:
        total_results = min(total_results, max_items)
        print(f"Limited to {total_results} items")

    # Process results in batches
    items_per_page = 150
    total_pages = (total_results + items_per_page - 1) // items_per_page

    skip_count = 0
    processed_count = 0

    for page in range(1, total_pages + 1):
        if processed_count >= total_results:
            break

        print(f"Processing page {page}/{total_pages}")

        # Rate limiting - wait before each API call
        if page > 1:  # Don't wait before the first request
            sleep(POLITE_WAIT_SECS)

        try:
            results = fetch_loc_results(
                collection_info["slug"], start_page=page, items_per_page=items_per_page
            )
        except Exception as e:
            tqdm.write(f"Error fetching page {page}: {e}")
            continue

        results_list = results.get("results", [])

        for result_item in tqdm(results_list, desc=f"Page {page}"):
            if processed_count >= total_results:
                break

            record = extract_image_data(result_item)

            # Skip if no ref (control number)
            if not record.get("ref"):
                tqdm.write("      ✗ No control number found, skipping")
                continue

            # Check if already exists
            existing_by_ref = Image.objects.filter(ref=record["ref"]).exists()
            if existing_by_ref:
                skip_count += 1
                continue
            elif skip_count > 0:
                tqdm.write(f"Skipped {skip_count} images that already exist")
                skip_count = 0

            # Get the highest quality image URL
            image_url = get_highest_quality_image_url(record)
            if not image_url:
                tqdm.write("      ✗ No image URL found, skipping")
                continue

            sleep(POLITE_WAIT_SECS)

            # Try downloading and uploading the image
            try:
                uploaded_url = r2_uploader.upload_url(
                    image_url,
                    in_tqdm=True,
                    raise_on_err=False,
                )
            except Exception as e:
                tqdm.write(f"      ✗ Error uploading image: {e}")
                continue

            if uploaded_url is None:
                tqdm.write("      ✗ Unable to download/upload image, skipping")
                continue

            # Create the image record
            try:
                tqdm.write(f"      → Inserting image {record['original_url']}")
                image = Image.objects.create(
                    collection=collection,
                    title=record["title"],
                    permalink=uploaded_url,
                    ref=record["ref"],
                    original_url=record["original_url"],
                    description=record.get("description", ""),
                    creator=record.get("creator", ""),
                    original_date=record.get("original_date"),
                    edtf_date=record.get("edtf_date"),
                )
                tqdm.write(f"      → Created image ID: {image.id}")
                processed_count += 1
            except Exception as e:
                tqdm.write(f"      ✗ Error creating image: {e}")
                continue

    print(f"\nProcessing complete. Processed {processed_count} images.")
    if skip_count > 0:
        print(f"Skipped {skip_count} existing images.")


if __name__ == "__main__":
    main()
