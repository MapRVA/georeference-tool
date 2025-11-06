#!/usr/bin/env python3
"""
VCU Collection Scraper

Usage:
    uv run scripts/importers/vcu.py <COLLECTION ID>
"""

import os
import sys
import re
import requests
from time import sleep
from tqdm import tqdm
import click

# Add the Django project to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(script_dir, "..", "..")
sys.path.insert(0, project_root)

# Change to project directory for Django
os.chdir(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "georeference_tool.settings")

import django

django.setup()

from images.models import Source, Collection, Image, PreCollection, PreImage

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

POLITE_WAIT_SECS = 0.75


def create_source_if_not_exist():
    """Get or create VCU Libraries source"""
    source, created = Source.objects.get_or_create(
        name="Virginia Commonwealth University",
        defaults={
            "url": "https://scholarscompass.vcu.edu/",
            "description": "Virginia Commonwealth University Libraries offer a wide variety of photo collections from throughout Richmond history.",
            "public": True,
        },
    )
    if created:
        print(f"Created source: {source.name}")
    else:
        print(f"Using existing source: {source.name}")
    return source


def create_collection_if_not_exist(source, collection_id, use_precollection=False):
    """Get or create a collection from the VCU collection page"""
    url = f"https://scholarscompass.vcu.edu/{collection_id}/"

    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching collection page: {e}")
        return None

    html_content = response.text

    # Extract collection name from the page
    name_match = re.search(
        r'<h1 id="series-title"><a[^>]*>(.*?)</a></h1>', html_content
    )
    collection_name = name_match.group(1) if name_match else collection_id

    # Extract description from intro section
    description_match = re.search(
        r'<div class="intro">(.*?)</div>', html_content, re.DOTALL
    )
    if description_match:
        # Strip HTML tags and clean up whitespace
        description = re.sub(r"<[^>]+>", "", description_match.group(1))
        description = re.sub(r"\s+", " ", description).strip()
    else:
        description = (
            f"Collection from Virginia Commonwealth University: {collection_id}"
        )

    # Check if collection already exists (check both types)
    if use_precollection:
        existing_collection = PreCollection.objects.filter(
            source=source, name=collection_name
        ).first()
        collection_type = "pre-collection"
    else:
        existing_collection = Collection.objects.filter(
            source=source, name=collection_name
        ).first()
        collection_type = "collection"

    if existing_collection:
        print(f"  ✓ Using existing {collection_type}: {existing_collection.name}")
        return existing_collection

    # Show collection details to user for confirmation
    print(f"\n  {collection_type.title()} Details for '{collection_id}':")
    print(f"  Name: {collection_name}")
    print(f"  Source: {source.name}")
    print(f"  URL: {url}")
    print(
        f"  Description: {description[:200]}..."
        if len(description) > 200
        else f"  Description: {description}"
    )
    if use_precollection:
        print(f"  Type: Pre-collection (for review)")

    if click.confirm(f"\n  Create this {collection_type}?"):
        if use_precollection:
            collection = PreCollection.objects.create(
                source=source,
                name=collection_name,
                url=url,
                description=description,
            )
        else:
            collection = Collection.objects.create(
                source=source,
                name=collection_name,
                url=url,
                description=description,
            )
        print(f"Created {collection_type}: {collection.name}")
        return collection
    else:
        return None


def get_image_ids_from_page_content(html_content, collection_id):
    """
    Parses page content to get a list of image IDs.
    """
    image_ids = re.findall(
        rf'href="https://scholarscompass.vcu.edu/{collection_id}/(\d+)"', html_content
    )
    unique_ids = sorted(list(set([int(id) for id in image_ids])))
    return unique_ids


def get_image_ids_from_page(url, collection_id):
    """
    Fetches a page and parses it to get a list of image IDs.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return []

    return get_image_ids_from_page_content(response.text, collection_id)


def extract_license_from_rights(html_content):
    """
    Extracts license information from the rights section.
    Returns a dict with 'license_title' and optionally 'license_permalink' if
    the public domain text is found.
    """
    # Extract the rights section
    rights_match = re.search(
        r"<div id='rights' class='element'>.*?<h2 class='field-heading'>Rights</h2>\s*<p>(.*?)</p>\s*</div>",
        html_content,
        re.DOTALL,
    )

    if not rights_match:
        return {}

    rights_text = rights_match.group(1).strip()

    # Check for public domain text
    if "This material is in the public domain in the United States and thus is free of any copyright restriction." in rights_text:
        return {"license_title": "Public Domain"}

    return {}


def get_image_details(
    image_id, collection_id, first_possible_year=None, last_possible_year=None
):
    """
    Fetches the details for a single image from its page.
    """
    url = f"https://scholarscompass.vcu.edu/{collection_id}/{image_id}/"
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

    html_content = response.text
    details = {"original_url": url}

    # --- File Name (used as ref) ---
    file_name_match = re.search(
        r"<div id='file_name' class='element'>\s*<h2 class='field-heading'>File Name</h2>\s*<p>(.*?)</p>\s*</div>",
        html_content,
        re.DOTALL,
    )
    if file_name_match:
        details["ref"] = file_name_match.group(1).strip()
    else:
        # Fallback to image_id if file name not found
        details["ref"] = str(image_id)

    # --- Title ---
    title_match = re.search(r"<h1><a href='[^']*'>(.*?)</a></h1>", html_content)
    if title_match:
        details["title"] = title_match.group(1)

    # --- Creator/Printer ---
    creator_match = re.search(
        r'<p class="author"><a[^>]*><strong>(.*?)</strong></a>', html_content
    )
    if creator_match:
        details["creator"] = creator_match.group(1)

    # --- Date ---
    # Try various date field patterns
    date_patterns = [
        r"<div id='publication_date' class='element'>\s*<h2 class='field-heading'>Date</h2>\s*<p>(.*?)</p>\s*</div>",
        r"<div id='publication_date' class='element'>\s*<h2 class='field-heading'>Publication Date</h2>\s*<p>(.*?)</p>\s*</div>",
        r"<div id='pub_date' class='element'>\s*<h2 class='field-heading'>Publication Date</h2>\s*<p>(.*?)</p>\s*</div>",
    ]

    date_str = None
    for pattern in date_patterns:
        date_match = re.search(pattern, html_content, re.DOTALL)
        if date_match:
            date_str = date_match.group(1).strip()
            # Skip if it says "Not postmarked" or similar
            if not re.match(r"^(Not|No|Unknown)", date_str, re.IGNORECASE):
                details["original_date"] = date_str
                break

    # --- Postmark Date (for description only) ---
    postmark_match = re.search(
        r"<div id='postmark_date' class='element'>\s*<h2 class='field-heading'>Postmark Date</h2>\s*<p>(.*?)</p>\s*</div>",
        html_content,
        re.DOTALL,
    )
    postmark_date = None
    if postmark_match:
        postmark_str = postmark_match.group(1).strip()
        if not re.match(r"^(Not|No|Unknown)", postmark_str, re.IGNORECASE):
            postmark_date = postmark_str

    # Parse the date if we found one
    if date_str and "original_date" in details:
        # Try to convert to EDTF format
        # MM-1-YYYY format (month-day-year with day always 1)
        if mm_dd_yyyy_match := re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", date_str):
            month = int(mm_dd_yyyy_match.group(1))
            day = int(mm_dd_yyyy_match.group(2))
            year = int(mm_dd_yyyy_match.group(3))

            # Validate that day is always 1 (false precision)
            if day != 1:
                print(f"\n✗ Image {image_id} has unexpected day value in date: {date_str}")
                print(f"  Expected day to be 1, but got {day}")
                sys.exit(1)

            # Convert month number to name for readable date
            month_names = ["", "January", "February", "March", "April", "May", "June",
                          "July", "August", "September", "October", "November", "December"]
            month_name = month_names[month] if 1 <= month <= 12 else None

            if month_name:
                details["original_date"] = f"{month_name} {year}"
                details["edtf_date"] = f"{year}-{month:02d}"
            else:
                print(f"\n✗ Image {image_id} has invalid month in date: {date_str}")
                print(f"  Month should be between 1 and 12, but got {month}")
                sys.exit(1)
        # YYYY format
        elif year_match := re.match(r"^(\d{4})$", date_str):
            details["edtf_date"] = year_match.group(1)
        # YYYY-YYYY range
        elif year_range_match := re.match(r"^(\d{4})\s*-\s*(\d{4})$", date_str):
            first_year = int(year_range_match.group(1))
            second_year = int(year_range_match.group(2))
            if second_year == (first_year + 1):
                details["edtf_date"] = f"[{first_year},{second_year}]"
            else:
                details["edtf_date"] = f"[{first_year}..{second_year}]"
        # Circa YYYY
        elif circa_match := re.match(r"(?i)(?:c|Circa|c\.)\s+(\d{4})$", date_str):
            details["edtf_date"] = circa_match.group(1) + "~"

    # If no date found, use fallback ranges if provided
    if "edtf_date" not in details:
        if first_possible_year and last_possible_year:
            details["edtf_date"] = f"[{first_possible_year}..{last_possible_year}]"
        elif first_possible_year:
            details["edtf_date"] = f"{first_possible_year}~"
        elif last_possible_year:
            details["edtf_date"] = f"{last_possible_year}~"

    # --- Description Fields ---
    description_parts = []

    def extract_field(field_id, field_name):
        match = re.search(
            rf"<div id='{field_id}' class='element'>\s*<h2 class='field-heading'>{field_name}</h2>\s*<p>(.*?)</p>\s*</div>",
            html_content,
            re.DOTALL,
        )
        if match:
            # Clean up whitespace and add to description
            text = re.sub(r"\s+", " ", match.group(1)).strip()
            description_parts.append(f"{field_name}:\n{text}")

    extract_field("abstract", "Card Text \\(transcribed from postcard\\)")
    extract_field("note", "Note")

    # Add postmark date if available
    if postmark_date:
        description_parts.append(f"Postmarked:\n{postmark_date}")

    extract_field("general_area_covered", "General Area Covered")
    extract_field("original_binder_label", "Original Binder Label")
    extract_field("subject_", "Subject")
    extract_field("city_location", "City/Location")

    if description_parts:
        details["description"] = "\n\n".join(description_parts)

    # --- Download URL ---
    internal_id_match = re.search(
        rf"/context/{collection_id}/article/(\d+)/type/native/viewcontent", html_content
    )
    if internal_id_match:
        internal_id = internal_id_match.group(1)
        details["permalink"] = (
            f"https://scholarscompass.vcu.edu/context/{collection_id}/article/{internal_id}/type/native/viewcontent"
        )

    # --- License ---
    license_info = extract_license_from_rights(html_content)
    details.update(license_info)

    return details


@click.command()
@click.argument("collection_id")
@click.option(
    "--max-pages", type=int, help="Maximum number of pages to scrape for image IDs."
)
@click.option(
    "--max-images", type=int, help="Maximum number of images to fetch details for."
)
@click.option(
    "--hotlink",
    is_flag=True,
    help="Hotlink images instead of uploading to R2 (creates pre-collection/pre-images)",
)
@click.option(
    "--first-possible-year",
    type=int,
    help="First possible year for images without dates (e.g., 1900)",
)
@click.option(
    "--last-possible-year",
    type=int,
    help="Last possible year for images without dates (e.g., 1930)",
)
def cli(
    collection_id,
    max_pages,
    max_images,
    hotlink,
    first_possible_year,
    last_possible_year,
):
    """
    Scrapes VCU collection and imports images into Django.

    COLLECTION_ID: The collection identifier (e.g., 'postcard', 'rca')
    """
    # Create source and collection
    source = create_source_if_not_exist()
    collection = create_collection_if_not_exist(
        source, collection_id, use_precollection=hotlink
    )

    if not collection:
        print("Collection creation cancelled or failed. Exiting.")
        return

    url = f"https://scholarscompass.vcu.edu/{collection_id}/"
    print(f"\nScraping {url} for image IDs...")

    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return

    html_content = response.text

    # Get total number of pages
    match = re.search(
        r"Page <strong>\d+</strong> of <strong>(\d+)</strong>", html_content
    )
    if not match:
        print("Could not find total number of pages. Scraping first page only.")
        num_pages = 1
    else:
        num_pages = int(match.group(1))
        print(f"Found {num_pages} pages in total.")

    if max_pages and num_pages > max_pages:
        num_pages = max_pages
        print(f"Limiting to {num_pages} pages as per --max-pages.")

    all_image_ids = []
    # Process first page
    all_image_ids.extend(get_image_ids_from_page_content(html_content, collection_id))

    if num_pages > 1:
        for page_num in tqdm(range(2, num_pages + 1), desc="Scraping page indexes"):
            page_url = f"{url.rstrip('/')}/index.{page_num}.html"

            try:
                response = requests.get(page_url)
                response.raise_for_status()
                sleep(POLITE_WAIT_SECS)
            except requests.exceptions.RequestException as e:
                print(f"\nError fetching {page_url}: {e}")
                continue

            page_html_content = response.text
            all_image_ids.extend(
                get_image_ids_from_page_content(page_html_content, collection_id)
            )

    all_image_ids = sorted(list(set(all_image_ids)))

    if max_images:
        all_image_ids = all_image_ids[:max_images]

    print(f"Found {len(all_image_ids)} unique image IDs to process.\n")

    # Initialize R2 uploader if not hotlinking
    r2_uploader = None if hotlink else R2Uploader()

    skip_count = 0
    non_public_domain_count = 0
    for image_id in tqdm(all_image_ids, desc="Processing images"):
        sleep(POLITE_WAIT_SECS)
        details = get_image_details(
            image_id,
            collection_id,
            first_possible_year=first_possible_year,
            last_possible_year=last_possible_year,
        )

        if not details:
            tqdm.write(f"      ✗ Failed to fetch details for image {image_id}")
            continue

        # Check for existing images by ref (file name) after fetching details
        if hotlink:
            existing_by_ref = PreImage.objects.filter(ref=details["ref"]).exists()
        else:
            existing_by_ref = Image.objects.filter(ref=details["ref"]).exists()

        if existing_by_ref:
            skip_count += 1
            continue
        elif skip_count > 0:
            tqdm.write(f"Skipped {skip_count} images that already exist")
            skip_count = 0

        # Check if we have required fields
        if "title" not in details:
            tqdm.write(f"      ✗ No title found for image {image_id}, skipping")
            continue

        if "permalink" not in details:
            tqdm.write(f"      ✗ No image URL found for image {image_id}, skipping")
            continue

        # Check if we have a valid EDTF date
        if "edtf_date" not in details:
            print(f"\n✗ Image {image_id} has no determinable date. Cannot continue.")
            print(f"  Title: {details.get('title')}")
            print(f"  Original date string: {details.get('original_date', 'N/A')}")
            print(f"\n  Please provide --first-possible-year and/or --last-possible-year")
            sys.exit(1)

        # Check if image is public domain
        if "license_title" not in details or details["license_title"] != "Public Domain":
            non_public_domain_count += 1
            continue

        # Try downloading the image (and uploading it to R2 if not hotlinking)
        if not hotlink:
            details["permalink"] = r2_uploader.upload_url(
                details["permalink"],
                in_tqdm=True,
                raise_on_err=False,
            )

        # Were we successful in downloading the image?
        if details["permalink"] is None:
            tqdm.write(f"      ✗ Unable to download image {image_id}, skipping")
            continue

        try:
            tqdm.write(f"      → Inserting image {details['original_url']}")

            # Create the appropriate image type based on hotlink option
            if hotlink:
                image = PreImage.objects.create(
                    collection=collection,
                    title=details["title"],
                    permalink=details["permalink"],
                    ref=details["ref"],
                    description=details.get("description", ""),
                    creator=details.get("creator", ""),
                    original_date=details.get("original_date"),
                    edtf_date=details.get("edtf_date"),
                    license_title=details.get("license_title"),
                )
                tqdm.write(f"      → Created pre-image ID: {image.id}")
            else:
                image = Image.objects.create(
                    collection=collection,
                    title=details["title"],
                    permalink=details["permalink"],
                    ref=details["ref"],
                    original_url=details["original_url"],
                    description=details.get("description", ""),
                    creator=details.get("creator", ""),
                    original_date=details.get("original_date"),
                    edtf_date=details.get("edtf_date"),
                    license_title=details.get("license_title"),
                )
                tqdm.write(f"      → Created image ID: {image.id}")
        except Exception as e:
            tqdm.write(f"      ✗ Error creating image: {e}")

    if skip_count > 0:
        print(f"\nSkipped {skip_count} images that already exist")

    if non_public_domain_count > 0:
        print(f"Skipped {non_public_domain_count} images that were not public domain")

    print("\n✓ Import complete!")


if __name__ == "__main__":
    cli()
