"""
Library of Congress Collection Scraper

New collections are PRIVATE, must be made public using admin interface.

Usage:
    uv run manage.py import library_of_congress

The script will interactively prompt for collection details.
"""

import re
from copy import copy
from time import sleep

import requests
from tqdm import tqdm

from images.models import Collection, Image, Source
from images.utils import R2Uploader

POLITE_WAIT_SECS = 3.0  # 3 seconds as requested for LoC rate limiting
R2_UPLOADER = R2Uploader()


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

    collection_slug = input(
        "Collection URL slug (e.g., 'detroit-publishing-company', 'sanborn-maps'): "
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
            print("\n⚠️  Found existing collection that may match this slug:")
            print(f"  Name: {matching_collection.name}")
            print(f"  URL: {matching_collection.url}")
            print(f"  Description: {matching_collection.description}")
            print(f"  Public: {'Yes' if matching_collection.public else 'No'}")
            print(f"  Images: {matching_collection.images.count()}")

            if input("\nUse this existing collection? [y/N] ").strip().lower() == "y":
                return {
                    "slug": collection_slug,
                    "name": matching_collection.name,
                    "description": matching_collection.description,
                    "existing_collection": matching_collection,
                }

    collection_name = input(
        "Collection display name (e.g., 'Detroit Publishing Company'): "
    )

    default_description = f"Images from the {collection_name} collection at the Library of Congress, filtered for Richmond, Virginia."
    collection_description = (
        input(f"Collection description [{default_description}]: ")
        or default_description
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
    print("\n  Collection Details:")
    print(f"  Name: {collection_name}")
    print(f"  Source: {source.name}")
    print(f"  URL: {collection_url}")
    print(f"  Description: {collection_info['description']}")

    if input("\n  Create this collection? [y/N] ").strip().lower() == "y":
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
    if len(record["creator"]) > 100:
        # To enforce max 100 character limit
        record["creator"] = record["creator"][:100]

    # Extract and process date - use item.date as primary source
    if item_data.get("date"):
        record["original_date"] = item_data["date"]
        record["edtf_date"] = parse_loc_date(item_data["date"])
    elif result_item.get("date"):
        record["original_date"] = result_item["date"]
        record["edtf_date"] = parse_loc_date(result_item["date"])
    elif item_data.get("created_published"):
        record["original_date"] = item_data["created_published"]
        record["edtf_date"] = parse_loc_date(item_data["created_published"])
    sub_photos = []
    for resource in result_item.get("resources", []):
        # In the case that an image is actually an album. This record will just be the first image
        if resource.get("files", 0) > 1:
            # Example result: https://www.loc.gov/resource/hhh.ca4637.sheet
            # Use https://www.loc.gov/resource/hhh.ca4637.sheet?st=list&fo=json to get list of segments
            resource_url = resource.get("url")
            if resource_url:
                resource_url += "?st=list&fo=json"
                res = requests.get(resource_url)
                res.raise_for_status()
                resource_data = res.json()
                segments = resource_data.get("segments", [])
                for segment in segments:
                    # TODO: "item" "latitude / longitude" in the "hh" collection can be used to create georeference hint. Could add to description?
                    #   can also check "place" list of dicts with lat lon field
                    if not re.search(r"^\d*\. ", segment["title"]):
                        subtitle = segment["title"]
                    else:
                        subtitle = re.sub(r"^\d*\. ", "", segment["title"])
                    sub_photos.append({
                        "title": subtitle,
                        "ref": record["ref"] + f'.{segment["index"]}',
                        "image_urls": segment["image_url"],
                        "id": segment["id"],
                    })
    record["sub_photos"] = sub_photos
    if record["original_date"].startswith("[") and record["original_date"].endswith(
        "]"
    ):
        record["original_date"] = record["original_date"][1:-1].strip()

    return record


def month_to_number(month_name):
    """Convert month name to number (1-12)"""
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
    return month_map.get(month_name.lower())


def parse_loc_date(date_str):
    """Parse Library of Congress date formats to EDTF"""
    if not date_str:
        return ""

    date_str = date_str.strip()

    # Remove square brackets if present
    if date_str.startswith("[") and date_str.endswith("]"):
        date_str = date_str[1:-1].strip()

    if date_str == "6-23-22 [23 June 23 1922]":
        return "1922-06-23"

    if date_str == "ca. 1861-ca. 1865, bulk 1865 April.":
        return "1861/1865~"

    if date_str == "1863, August 23; c1882 Nov. 14.":
        return "1863-08-23"

    # Handle simple year "1905"
    year_match = re.match(r"^(\d{4})\.?$", date_str)
    if year_match:
        return year_match.group(1)

    # Handle uncertain year "1905?"
    year_match = re.match(r"^(\d{4})\?$", date_str)
    if year_match:
        return year_match.group(1) + "?"

    # Handle complex circa patterns with embedded brackets and question marks
    # Examples: "c[1901?]", "c1901?", etc.
    complex_circa_match = re.match(r"^c\[?(\d{4})\??\.?\]?$", date_str)
    if complex_circa_match:
        return complex_circa_match.group(1) + "~"

    # Handle "YYYY Month" format
    ca_year_month = re.match(r"^\[?(\d{4})\]?\s+(\w+)\.?$", date_str, re.IGNORECASE)
    if ca_year_month:
        year = ca_year_month.group(1)
        month = month_to_number(ca_year_month.group(2))
        if month:
            return f"{year}-{month:02d}"

    # Handle "YYYY ca. Month" format
    ca_year_month = re.match(r"^(\d{4})\s+ca?\.\s+(\w+)$", date_str, re.IGNORECASE)
    if ca_year_month:
        year = ca_year_month.group(1)
        month = month_to_number(ca_year_month.group(2))
        if month:
            return f"{year}-{month:02d}~"

    # Handle "Month YYYY" format
    month_year_match = re.match(
        r"^(\w+)\.?\s+\[?(\d{4})\]?\.?$", date_str, re.IGNORECASE
    )
    if month_year_match:
        month = month_to_number(month_year_match.group(1))
        year = month_year_match.group(2)
        if month:
            return f"{year}-{month:02d}"

    # Handle uncertain "Month YYYY?" format
    uncertain_month_year_match = re.match(
        r"^(\w+)\.?\s+\[?(\d{4})\]?\.?\?$", date_str, re.IGNORECASE
    )
    if uncertain_month_year_match:
        month = month_to_number(uncertain_month_year_match.group(1))
        year = uncertain_month_year_match.group(2)
        if month:
            return f"{year}-{month:02d}?"

    # Handle "YYYY Month DD" format
    year_month_day_match = re.match(
        r"^(\d{4})\s+(\w+)\s+(\d{1,2})\.?$", date_str, re.IGNORECASE
    )
    if year_month_day_match:
        year = year_month_day_match.group(1)
        month = month_to_number(year_month_day_match.group(2))
        day = int(year_month_day_match.group(3))
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    # Handle "YYYY ca. Month DD" format
    ca_month_day_match = re.match(
        r"^(\d{4})\s+ca?\.\s+(\w+)\s+(\d{1,2})$", date_str, re.IGNORECASE
    )
    if ca_month_day_match:
        year = ca_month_day_match.group(1)
        month = month_to_number(ca_month_day_match.group(2))
        day = int(ca_month_day_match.group(3))
        if month:
            return f"{year}-{month:02d}-{day:02d}~"

    # Handle "YYYY Month-Month" format
    month_range_match = re.match(
        r"^(\d{4})\s+\[?(\w+)-([A-Za-z]+)\]?$", date_str, re.IGNORECASE
    )
    if month_range_match:
        year = month_range_match.group(1)
        month1 = month_to_number(month_range_match.group(2))
        month2 = month_to_number(month_range_match.group(3))
        if month1 and month2:
            return f"{year}-{month1:02d}/{year}-{month2:02d}"

    # Handle "YYYY ca. Month-Month" format
    ca_month_range_match = re.match(
        r"^(\d{4})\s+ca?\.\s+(\w+)-(\w+)$", date_str, re.IGNORECASE
    )
    if ca_month_range_match:
        year = ca_month_range_match.group(1)
        month1 = month_to_number(ca_month_range_match.group(2))
        month2 = month_to_number(ca_month_range_match.group(3))
        if month1 and month2:
            return f"{year}-{month1:02d}/{year}-{month2:02d}~"

    # Handle "ca." or "circa" followed by year
    ca_match = re.match(r"^(?:ca\.|circa)\s+(\d{4})$", date_str, re.IGNORECASE)
    if ca_match:
        return ca_match.group(1) + "~"

    # Handle "c1905" or "c1905." format (circa dates with optional period)
    circa_match = re.match(r"^c(\d{4})\.?$", date_str)
    if circa_match:
        return circa_match.group(1) + "~"

    # Handle "between YYYY and YYYY" format
    between_match = re.match(
        r"^between (\d{4}) and (\d{4})(?:,\s*\[?printed\s+later\]?)?$",
        date_str,
        re.IGNORECASE,
    )
    if between_match:
        return between_match.group(1) + "/" + between_match.group(2)

    # Handle "between YYYY and YYYY uncertain" format
    between_uncertain_match = re.match(
        r"^between (\d{4}) and (\d{4})\?$", date_str, re.IGNORECASE
    )
    if between_uncertain_match:
        return (
            between_uncertain_match.group(1)
            + "/"
            + between_uncertain_match.group(2)
            + "?"
        )

    # Handle "between YYYY Month and YYYY Month" format
    between_month_match = re.match(
        r"^between (\d{4}) (\w+) and (\d{4}) (\w+)[,?\s+\[?printed later\]?]?$",
        date_str,
        re.IGNORECASE,
    )
    if between_month_match:
        start_year = between_month_match.group(1)
        start_month = month_to_number(between_month_match.group(2))
        end_year = between_month_match.group(3)
        end_month = month_to_number(between_month_match.group(4))
        if start_month and end_month:
            return f"{start_year}-{start_month:02d}/{end_year}-{end_month:02d}"

    # Handle "c between YYYY and YYYY" format
    circa_between_match = re.match(
        r"^c\[?between (\d{4}) and (\d{4})\]?$", date_str, re.IGNORECASE
    )
    if circa_between_match:
        return circa_between_match.group(1) + "/" + circa_between_match.group(2) + "~"

    # Handle "between ca.YYYY and YYYY" format
    circa_between_match_2 = re.match(
        r"^\[?between ca?\.?(\d{4}) and (\d{4})\]?$", date_str, re.IGNORECASE
    )
    if circa_between_match_2:
        return (
            circa_between_match_2.group(1) + "/" + circa_between_match_2.group(2) + "~"
        )

    # Handle "YYYY Month, c<published month>" format
    year_month_day_match = re.match(
        r"^(\d{4})\s+(\w+)(?:,\s+c\w+|\s+\[printed later\](?:,\s+c\d{4}\.)?)\.?$",
        date_str,
        re.IGNORECASE,
    )
    if year_month_day_match:
        year = year_month_day_match.group(1)
        month = month_to_number(year_month_day_match.group(2))
        if month:
            return f"{year}-{month:02d}"

    # Handle "YYYY Month Day - <published month>" format
    year_month_day__published_match = re.match(
        r"^(\d{4})\s+(\w+)\s+(\d{1,2})\s+-\s+\w+$", date_str, re.IGNORECASE
    )
    if year_month_day__published_match:
        year = year_month_day__published_match.group(1)
        month = month_to_number(year_month_day__published_match.group(2))
        day = int(year_month_day__published_match.group(3))
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    year_printed_date_match = re.match(
        r"^photographed (\d{4}), \[?printed[\s\w]+\]?$", date_str
    )
    if year_printed_date_match:
        year = year_printed_date_match.group(1)
        return f"{year}"

    month_year_printed_date_match = re.match(
        r"^(?:photographed )?(\w+),?\s+(\d{4}), \[?printed[\s\w]+\]?$", date_str
    )
    if month_year_printed_date_match:
        month = month_to_number(month_year_printed_date_match.group(1))
        year = month_year_printed_date_match.group(2)
        if month:
            return f"{year}-{month:02d}"

    year_printed_year_match = re.match(
        r"^(?:photographed\s+)?(\d{4}),\s+c?\d{4}$", date_str
    )
    if year_printed_year_match:
        return year_printed_year_match.group(1)

    year_reproduced_year_match = re.match(
        r"^(?:photographed\s+)?(\d{4}),\s+reproduced\s+c?a?\.?\s*\d{4}$", date_str
    )
    if year_reproduced_year_match:
        return year_reproduced_year_match.group(1)

    year_month_printed_date_match = re.match(
        r"^(?:photographed )?(\d{4}),?\s+(\w+), \[?printed[\s\w]+\]?$", date_str
    )
    if year_month_printed_date_match:
        year = year_month_printed_date_match.group(1)
        month = month_to_number(year_month_printed_date_match.group(2))
        if month:
            return f"{year}-{month:02d}"

    year_range_printed_match = re.match(
        r"^photographed between (\d{4}) and (\d{4}), \[?printed[\s\w]+\]?$", date_str
    )
    if year_range_printed_match:
        return (
            year_range_printed_match.group(1) + "/" + year_range_printed_match.group(2)
        )

    # Handle year ranges "1905-1910"
    range_match = re.match(r"^(\d{4})-(\d{4})$", date_str)
    if range_match:
        return range_match.group(1) + "/" + range_match.group(2)

    # Handle uncertain year ranges "1905-1910?"
    range_match = re.match(r"^(\d{4})-(\d{4})\?$", date_str)
    if range_match:
        return range_match.group(1) + "/" + range_match.group(2) + "?"

    # Handle "1905-01-01" ISO format
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
    if iso_match:
        return date_str
    # Found in the "hh" collection
    compiled_match = re.match(r"^Documentation compiled after (\d{4})$", date_str)
    if compiled_match:
        return compiled_match.group(1)

    # If we can't parse it, breakpoint
    breakpoint()


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


def create_image(record, collection, license_):
    # Check if already exists
    existing_by_ref = Image.objects.filter(ref=record["ref"]).exists()
    if existing_by_ref:
        return "skipped"

    # Get the highest quality image URL
    image_url = get_highest_quality_image_url(record)
    if not image_url:
        tqdm.write("      ✗ No image URL found, skipping")
        return "no image"

    sleep(POLITE_WAIT_SECS)

    # Try downloading and uploading the image
    try:
        uploaded_url = R2_UPLOADER.upload_url(
            image_url,
            in_tqdm=True,
            raise_on_err=False,
        )
    except Exception as e:
        tqdm.write(f"      ✗ Error uploading image: {e}")
        return

    if uploaded_url is None:
        tqdm.write("      ✗ Unable to download/upload image, skipping")
        return

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
            license=license_,
        )
        tqdm.write(f"      → Created image ID: {image.id}")
        return "processed"
    except Exception as e:
        tqdm.write(f"      ✗ Error creating image: {e}")
        return "error"


def add_arguments(parser):
    """Add library_of_congress-specific arguments to the parser."""
    parser.add_argument(
        "--max-items", type=int, default=None, help="Maximum number of items to process"
    )


def handle(options):
    """Run the Library of Congress import."""
    max_items = options["max_items"]

    source = create_source_if_not_exist()
    collection_info = get_collection_info()
    collection = create_collection_if_not_exist(source, collection_info)

    if not collection:
        print("Collection creation cancelled.")
        return

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

            if record["sub_photos"]:
                for sub_photo in record["sub_photos"]:
                    # Replace some fields with the sub photo fields
                    sub_record = copy(record).update(sub_photo)
                    result = create_image(sub_record, collection, options.get("license"))
                    if result == "skipped":
                        skip_count += 1
                    elif skip_count > 0:
                        tqdm.write(f"Skipped {skip_count} images that already exist")
                        skip_count = 0
                    elif result == "processed":
                        processed_count += 1
            else:
                result = create_image(record, collection, options.get("license"))
                if result == "skipped":
                    skip_count += 1
                elif skip_count > 0:
                    tqdm.write(f"Skipped {skip_count} images that already exist")
                    skip_count = 0
                elif result == "processed":
                    processed_count += 1


    print(f"\nProcessing complete. Processed {processed_count} images.")
    if skip_count > 0:
        print(f"Skipped {skip_count} existing images.")
