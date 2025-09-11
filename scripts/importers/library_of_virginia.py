#!/usr/bin/env python3
"""
Library of Virginia Richmond Esthetic Survey (RES) Scraper

Scrapes the 3-level RES structure:
1. Hard-coded area links (A, B, C, D)
2. Parse area pages for neighborhood dropdown URLs
3. Parse neighborhood pages for image data

Usage:
    python library_of_virginia.py --area A --dry-run
    python library_of_virginia.py --area ALL --max-neighborhoods 2 --dry-run
"""

# All images from the Library of Virginia RES are from 1965
SOURCE_YEAR = 1965

import argparse
import os
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

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


class LibraryOfVirginiaScraper:
    """Richmond Esthetic Survey scraper"""

    # Hard-coded area URLs (Level 1)
    AREA_URLS = {
        "A": "https://image.lva.virginia.gov/cgi-bin/res/res.pl?ox=0&oy=0&filename=LVA_maps15.sid&title=Area+A%3Cbr%3EFan+District,+VCU+area,+and+Oregon+Hill&res=3&size=12&default_x=3462.5&default_y=3622.5&fullwidth=6925&fullheight=7245",
        "B": "https://image.lva.virginia.gov/cgi-bin/res/res.pl?ox=0&oy=0&filename=LVA_maps16.sid&title=Area+B%3Cbr%3EJackson+Ward,+MCV+area,+Navy+Hill,+Carver,+Gilpin+Court&res=3&size=12&default_x=3076&default_y=3947.5&fullwidth=6152&fullheight=7895",
        "C": "https://image.lva.virginia.gov/cgi-bin/res/res.pl?ox=0&oy=0&filename=LVA_maps16.sid&title=Area+C%3Cbr%3ECapitol+Square,+Financial+District,+Shockoe+Slip,+Monroe+Ward,+Gamble%39s+Hill&res=3&size=12&default_x=3076&default_y=3947.5&fullwidth=6152&fullheight=7895",
        "D": "https://image.lva.virginia.gov/cgi-bin/res/res.pl?ox=0&oy=0&filename=LVA_maps17.sid&title=Area+D%3Cbr%3EChurch+Hill,+Shockoe+Bottom,+Shockoe+Valley,+Fulton&res=3&size=12&default_x=3014&default_y=3485.5&fullwidth=6028&fullheight=6971",
    }

    def __init__(self):
        self.session = requests.Session()
        self.r2_uploader = R2Uploader()

    def clean_image_url(self, url):
        """Remove square brackets from image URLs"""
        return url.replace("[", "").replace("]", "")

    def get_or_create_source(self):
        """Get or create the Library of Virginia source"""
        source, created = Source.objects.get_or_create(
            name="Library of Virginia",
            defaults={
                "url": "https://image.lva.virginia.gov/",
                "description": "The Library of Virginia is the archival agency and reference library for Virginia's government, housing the most comprehensive collection of materials on Virginia history. Founded in 1823, it preserves over 134 million items including government records, photographs, maps, and personal papers dating back to the colonial period.",
                "public": True,
            },
        )
        if created:
            print(f"✓ Created source: {source.name}")
        else:
            print(f"✓ Using existing source: {source.name}")
        return source

    def get_or_create_collection(self, source, collection_name, collection_url):
        """Get or create a collection for the given neighborhood"""
        collection, created = Collection.objects.get_or_create(
            source=source,
            name=collection_name,
            defaults={
                "url": collection_url,
                "description": "Part of the 1965 Richmond Esthetic Survey and Historic Building Survey, documenting buildings and locations across Richmond.",
                "public": True,
            },
        )
        if created:
            print(f"  ✓ Created collection: {collection.name}")
        else:
            print(f"  ✓ Using existing collection: {collection.name}")
        return collection

    def fetch_page(self, url):
        """Fetch a web page with error handling"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            print(f"  ✗ Error fetching {url}: {e}")
            return None

    def parse_area_page(self, area_url):
        """Parse area page (Level 2) to extract neighborhood URLs"""
        print("  Parsing area page...")
        response = self.fetch_page(area_url)
        if not response:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        neighborhoods = []

        # Find the neighborhoods dropdown
        neighborhoods_select = soup.find("select", {"name": "neighborhoods"})
        if not neighborhoods_select:
            print("  ✗ No neighborhoods dropdown found")
            return []

        # Extract neighborhood options
        for option in neighborhoods_select.find_all("option"):
            value = option.get("value", "").strip()
            text = option.get_text().strip()

            if value and value != "" and "Select" not in text:
                # Extract neighborhood name from text like "W. Franklin St. and Monument Ave. (A001)"
                neighborhood_name = text.strip()
                # Ensure URL uses HTTPS
                url_value = value.replace("http://", "https://")
                neighborhoods.append({"url": url_value, "name": neighborhood_name})

        print(f"  ✓ Found {len(neighborhoods)} neighborhoods")
        return neighborhoods

    def parse_neighborhood_page(self, neighborhood_url):
        """Parse neighborhood page (Level 3) to extract image data"""
        response = self.fetch_page(neighborhood_url)
        if not response:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        images = []

        # Find all image links in the "Neighborhood View Photographs" section
        # Look for links to /RES/access/sp/ images
        for link in soup.find_all("a", href=True):
            href = link.get("href")
            if href and ("/RES/access/sp/" in href or "/RES/access/up/" in href):
                # Get the full image URL
                full_image_url = urljoin(neighborhood_url, href)
                # Ensure image URL uses HTTPS
                full_image_url = full_image_url.replace("http://", "https://")
                # Clean square brackets from URL
                full_image_url = self.clean_image_url(full_image_url)

                # Find the title by looking at the parent td element
                parent_td = link.find_parent("td")
                title = ""

                if parent_td:
                    # Get all text from the td, then clean it up
                    td_text = parent_td.get_text(separator=" ").strip()

                    # Split by lines and look for the title (usually the second line)
                    lines = [
                        line.strip() for line in td_text.split("\n") if line.strip()
                    ]

                    # The title is usually between the image and the "Photo Record" link
                    for line in lines:
                        if (
                            line
                            and not line.startswith("<")
                            and "Photo Record" not in line
                        ):
                            # Remove quotes, stray ">" characters, and clean up whitespace
                            title = line.strip('"').strip()
                            title = (
                                title.rstrip(">").strip()
                            )  # Remove trailing ">" and any remaining whitespace
                            if title:  # Take the first good title we find
                                break

                if title:
                    images.append(
                        {
                            "url": full_image_url,
                            "title": title,
                            "original_url": full_image_url,  # Store original URL
                            "permalink": full_image_url,  # Will be updated to R2 URL later
                        }
                    )

        print(f"    ✓ Found {len(images)} images")
        return images

    def scrape_area(
        self, area_code, max_neighborhoods=None, max_images=None, dry_run=False
    ):
        """Scrape a specific area"""
        if area_code not in self.AREA_URLS:
            print(f"✗ Unknown area code: {area_code}")
            return

        print(f"\n=== Scraping Area {area_code} ===")
        area_url = self.AREA_URLS[area_code]

        # Get or create Django source
        source = self.get_or_create_source()

        # Parse area page to get neighborhoods
        neighborhoods = self.parse_area_page(area_url)
        if not neighborhoods:
            print(f"✗ No neighborhoods found for area {area_code}")
            return

        if max_neighborhoods:
            neighborhoods = neighborhoods[:max_neighborhoods]
            print(f"  → Limited to {len(neighborhoods)} neighborhoods")

        total_imported = 0

        # Process each neighborhood
        for i, neighborhood in enumerate(neighborhoods, 1):
            print(f"\n  [{i}/{len(neighborhoods)}] Processing: {neighborhood['name']}")

            # Get or create collection
            # Ensure URL uses HTTPS
            collection_url = neighborhood["url"].replace("http://", "https://")
            collection = self.get_or_create_collection(
                source, neighborhood["name"], collection_url
            )

            # Parse neighborhood page to get images
            images = self.parse_neighborhood_page(neighborhood["url"])

            if max_images:
                images = images[:max_images]
                print(f"    → Limited to {len(images)} images")

            # Process each image
            imported_count = 0
            for j, image_data in enumerate(images, 1):
                print(f"    [{j}/{len(images)}] {image_data['title']}")

                # Upload image to R2 if uploader is available
                if self.r2_uploader and not dry_run:
                    print("      → Uploading to R2...")
                    image_data["permalink"] = self.r2_uploader.upload_url(
                        image_data["url"],
                    )
                elif self.r2_uploader and dry_run:
                    print("      → Would upload to R2 (dry run)")
                    # For dry run, generate what the R2 URL would look like
                    mock_key = self.r2_uploader.generate_key_from_url(
                        image_data["url"],
                    )
                    image_data["permalink"] = self.r2_uploader.get_public_url(mock_key)

                # Check if already exists (check by original URL)
                existing_by_original_url = Image.objects.filter(
                    original_url=image_data["original_url"]
                ).exists()
                # Also check by permalink in case of duplicates with different R2 URLs
                existing_by_permalink = Image.objects.filter(
                    permalink=image_data["permalink"]
                ).exists()

                if existing_by_original_url or existing_by_permalink:
                    print("      → Already exists, skipping")
                    continue

                if not dry_run:
                    try:
                        image = Image.objects.create(
                            collection=collection,
                            title=image_data["title"],
                            permalink=image_data["permalink"],
                            original_url=image_data["original_url"],
                            year=SOURCE_YEAR,
                        )
                        print(f"      → Created image ID: {image.id}")
                        imported_count += 1
                    except Exception as e:
                        print(f"      ✗ Error creating image: {e}")
                else:
                    print("      → Would create image (dry run)")
                    imported_count += 1

                # Be nice to the server
                time.sleep(0.5)

            print(
                f"    ✓ {'Would import' if dry_run else 'Imported'} {imported_count} new images"
            )
            total_imported += imported_count

        print(f"\n=== Area {area_code} Complete ===")
        print(f"Neighborhoods processed: {len(neighborhoods)}")
        print(
            f"{'Would import' if dry_run else 'Imported'}: {total_imported} total images"
        )

    def scrape_all_areas(self, max_neighborhoods=None, max_images=None, dry_run=False):
        """Scrape all areas A, B, C, D"""
        print("\n=== Scraping ALL Areas (A, B, C, D) ===")
        for area_code in ["A", "B", "C", "D"]:
            self.scrape_area(area_code, max_neighborhoods, max_images, dry_run)
            time.sleep(2)  # Longer delay between areas


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Richmond Esthetic Survey from Library of Virginia"
    )
    parser.add_argument(
        "--area",
        required=True,
        choices=["A", "B", "C", "D", "ALL"],
        help="Area to scrape (A, B, C, D, or ALL)",
    )
    parser.add_argument(
        "--max-neighborhoods",
        type=int,
        help="Maximum number of neighborhoods to process per area (for testing)",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        help="Maximum number of images to process per neighborhood (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without actually importing",
    )

    args = parser.parse_args()

    scraper = LibraryOfVirginiaScraper()

    if args.area == "ALL":
        scraper.scrape_all_areas(
            max_neighborhoods=args.max_neighborhoods,
            max_images=args.max_images,
            dry_run=args.dry_run,
        )
    else:
        scraper.scrape_area(
            area_code=args.area,
            max_neighborhoods=args.max_neighborhoods,
            max_images=args.max_images,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
