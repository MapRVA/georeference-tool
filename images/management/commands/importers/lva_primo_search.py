"""
LVA Primo Collection Scraper

Usage:
    uv run manage.py import lva_primo_search
"""

import csv
import json
import os
import re
import time
from time import sleep

import requests
from tqdm import tqdm

from images.models import Collection, Image, PreCollection, PreImage, Source
from images.utils import R2Uploader


class PrimoAPIClient:
    def __init__(self, base_url="https://lva.primo.exlibrisgroup.com"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.5",
                "DNT": "1",
                "Connection": "keep-alive",
            }
        )
        self.bearer_token = None
        self.api_base = f"{self.base_url}/primaws/rest/pub/pnxs"

    def get_session_token(self, search_url):
        """
        Get a valid Bearer token by loading the search page first
        """
        print("Getting session token...")

        try:
            # First, load the main search page to establish session
            response = self.session.get(search_url)
            response.raise_for_status()

            # Look for bearer token in the page JavaScript
            token_patterns = [
                r"Bearer\s+([A-Za-z0-9\-_\.]+)",
                r'authorization["\']:\s*["\']Bearer\s+([A-Za-z0-9\-_\.]+)["\']',
                r'token["\']:\s*["\']([A-Za-z0-9\-_\.]+)["\']',
            ]

            for pattern in token_patterns:
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                if matches:
                    token = matches[0]
                    if len(token) > 50:  # JWT tokens are typically long
                        self.bearer_token = token
                        print(f"Found Bearer token: {token[:20]}...")
                        return True

            print("No Bearer token found in page source")
            return False

        except requests.RequestException as e:
            print(f"Error getting session: {e}")
            return False

    def search_with_token(self, query_params):
        """
        Make API request with Bearer token
        """
        if not self.bearer_token:
            print("No Bearer token available")
            return None

        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "Accept": "application/json, text/plain, */*",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            print(f"Making API request to: {self.api_base}")
            print(f"Parameters: {query_params}")

            response = self.session.get(
                self.api_base, params=query_params, headers=headers
            )

            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    return data
                except json.JSONDecodeError:
                    print("Response is not valid JSON")
                    print(f"Response content: {response.text[:500]}")
                    return None
            else:
                print(f"API request failed: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                return None

        except requests.RequestException as e:
            print(f"Error making API request: {e}")
            return None

    def search_without_auth(self, query_params):
        """
        Try API request without authentication (might work for some endpoints)
        """
        print("Trying API request without authentication...")

        try:
            response = self.session.get(self.api_base, params=query_params)
            print(f"No-auth response status: {response.status_code}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    return data
                except json.JSONDecodeError:
                    print("Response is not valid JSON")
                    return None
            else:
                print(f"No-auth request failed: {response.status_code}")
                return None

        except requests.RequestException as e:
            print(f"Error making no-auth request: {e}")
            return None

    def search_collection(self, collection_name, vid, limit=10, offset=0):
        """
        Search for a specific collection
        """
        # Build query parameters based on the working curl command
        query_params = {
            "acTriggered": "false",
            "disableCache": "false",
            "getMore": "0",
            "inst": vid.split(":")[0],  # Extract institution from vid
            "isCDSearch": "false",
            "lang": "en",
            "limit": str(limit),
            "mode": "advanced",
            "newspapersActive": "true",
            "newspapersSearch": "false",
            "offset": str(offset),
            "q": f"title,exact,{collection_name},AND",
            "qExclude": "",
            "qInclude": "",
            "refEntryActive": "false",
            "rtaLinks": "true",
            "scope": "MyInstitution",
            "skipDelivery": "N",
            "tab": "LibraryCatalog",
            "vid": vid,
        }

        # First try with authentication
        search_url = f"{self.base_url}/discovery/search"
        if self.get_session_token(search_url):
            result = self.search_with_token(query_params)
            if result:
                return result

        # Fallback: try without authentication
        return self.search_without_auth(query_params)

    def get_iiif_url_from_manifest(self, ie_number):
        """
        Get the IIIF image URL from the manifest
        """
        manifest_url = f"https://rosetta.virginiamemory.com/delivery/iiif/presentation/2.1/IE{ie_number}/manifest"
        try:
            # Use a new session for each request to avoid state issues
            with requests.Session() as session:
                session.headers.update(
                    {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                    }
                )
                response = session.get(manifest_url, timeout=15)
                if response.status_code != 200:
                    print(
                        f"Error fetching manifest for IE{ie_number}: Status {response.status_code}, Response: {response.text[:200]}"
                    )
                    return None

                manifest = response.json()

                if "sequences" in manifest and len(manifest["sequences"]) > 0:
                    sequence = manifest["sequences"][0]
                    if "canvases" in sequence and len(sequence["canvases"]) > 0:
                        canvas = sequence["canvases"][0]
                        if "images" in canvas and len(canvas["images"]) > 0:
                            image_info_url = canvas["images"][0]["resource"]["@id"]

                            # Fetch the image info JSON
                            info_response = session.get(image_info_url, timeout=15)
                            if info_response.status_code != 200:
                                print(
                                    f"Error fetching image info for IE{ie_number}: Status {info_response.status_code}, Response: {info_response.text[:200]}"
                                )
                                return None

                            image_info = info_response.json()

                            if (
                                "service" in image_info
                                and "@id" in image_info["service"]
                            ):
                                service_id = image_info["service"]["@id"]
                                return f"{service_id}/full/max/0/default.jpg"

        except (
            requests.RequestException,
            json.JSONDecodeError,
            KeyError,
            IndexError,
        ) as e:
            print(f"Error processing manifest for IE{ie_number}: {e}")

        return None

    def extract_records(self, api_response, existing_refs=None):
        """
        Extract useful information from API response and generate IIIF URLs
        """
        if existing_refs is None:
            existing_refs = set()
        if not api_response:
            return []

        records = []

        # The response structure may vary, let's handle different cases
        if "docs" in api_response:
            docs = api_response["docs"]
        elif "info" in api_response and "docs" in api_response["info"]:
            docs = api_response["info"]["docs"]
        else:
            print("Unknown response structure:")
            print(json.dumps(api_response, indent=2)[:500])
            return []

        for doc in tqdm(docs, desc="Processing records and fetching IIIF URLs"):
            record = {}

            # Extract PNX data (Primo Normalized XML)
            if "pnx" in doc:
                pnx = doc["pnx"]

                # Display section has human-readable data
                if "display" in pnx:
                    display = pnx["display"]
                    record["title"] = (
                        display.get("title", [""])[0] if display.get("title") else ""
                    )
                    record["creator"] = (
                        display.get("creator", [""])[0]
                        if display.get("creator")
                        else ""
                    )
                    record["date"] = (
                        display.get("creationdate", [""])[0]
                        if display.get("creationdate")
                        else ""
                    )
                    record["type"] = (
                        display.get("type", [""])[0] if display.get("type") else ""
                    )
                    record["format"] = (
                        display.get("format", [""])[0] if display.get("format") else ""
                    )

                    # Extract description (multiple possible fields)
                    descriptions = display.get("description", [])
                    record["description"] = (
                        " | ".join(descriptions) if descriptions else ""
                    )

                    # Extract identifiers for reference numbers and IIIF URLs
                    identifiers = display.get("identifier", [])
                    record["identifiers"] = identifiers

                    # Parse identifiers for reference numbers and IE numbers
                    record["reference_number"] = ""
                    record["digitool_id"] = ""
                    record["ie_number"] = ""

                    for identifier in identifiers:
                        # C&J reference number
                        cj_match = re.search(r"C&J (\d+)", identifier)
                        if cj_match:
                            record["reference_number"] = f"C&J {cj_match.group(1)}"

                        # Digitool ID
                        digitool_match = re.search(r"digitool\)(\d+)", identifier)
                        if digitool_match:
                            record["digitool_id"] = digitool_match.group(1)

                        # IE number for IIIF URL construction
                        ie_match = re.search(r"IE(\d+)", identifier)
                        if ie_match:
                            record["ie_number"] = ie_match.group(1)

                # Control section has IDs and technical data
                if "control" in pnx:
                    control = pnx["control"]
                    record["record_id"] = (
                        control.get("recordid", [""])[0]
                        if control.get("recordid")
                        else ""
                    )
                    record["source_id"] = (
                        control.get("sourceid", [""])[0]
                        if control.get("sourceid")
                        else ""
                    )

                ref = record.get("reference_number") or record.get("record_id")
                if ref and ref in existing_refs:
                    continue

                # Generate IIIF URLs if we have IE number
                if record["ie_number"]:
                    iiif_url = self.get_iiif_url_from_manifest(record["ie_number"])
                    if iiif_url:
                        record["iiif_full_url"] = iiif_url
                        record["iiif_thumbnail_url"] = iiif_url.replace(
                            "/full/max/", "/full/300,/"
                        )
                        record["iiif_medium_url"] = iiif_url.replace(
                            "/full/max/", "/full/800,/"
                        )
                    else:
                        record["iiif_full_url"] = ""
                        record["iiif_thumbnail_url"] = ""
                        record["iiif_medium_url"] = ""
                else:
                    record["iiif_full_url"] = ""
                    record["iiif_thumbnail_url"] = ""
                    record["iiif_medium_url"] = ""

                # Add full PNX for detailed analysis
                record["full_pnx"] = pnx

            # Extract delivery information (might contain access URLs)
            if "delivery" in doc:
                record["delivery"] = doc["delivery"]

            records.append(record)

        return records

    def validate_iiif_urls(self, records, sample_size=5):
        """
        Validate a sample of IIIF URLs to ensure they work
        """
        print(f"Validating {sample_size} IIIF URLs...")

        records_with_iiif = [r for r in records if r.get("iiif_full_url")]
        if not records_with_iiif:
            print("No records with IIIF URLs found")
            return 0

        sample_records = records_with_iiif[:sample_size]
        working_count = 0

        for i, record in enumerate(sample_records):
            url = record["iiif_full_url"]
            title = record["title"][:50]

            try:
                response = self.session.head(url, timeout=10)
                if response.status_code == 200 and "image/" in response.headers.get(
                    "content-type", ""
                ):
                    print(f"  \u2713 {i + 1}. {title} - WORKING")
                    working_count += 1
                else:
                    print(
                        f"  \u2717 {i + 1}. {title} - FAILED ({response.status_code})"
                    )
            except Exception as e:
                print(f"  \u2717 {i + 1}. {title} - ERROR ({e})")

        success_rate = (working_count / sample_size) * 100
        print(
            f"Validation result: {working_count}/{sample_size} working ({success_rate:.1f}%)"
        )
        return working_count

    def save_results(self, records, filename="primo_api_results.json"):
        """
        Save extracted records to file with enhanced metadata and IIIF URLs
        """
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(records)} records to {filename}")

        # Create CSV for easy viewing
        csv_file = filename.replace(".json", ".csv")
        self.save_csv(records, csv_file)

        # Also save a human-readable summary
        summary_file = filename.replace(".json", "_summary.txt")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write("Primo Search Results Summary\n")
            f.write(f"{'=' * 40}\n\n")
            f.write(f"Total records: {len(records)}\n")

            records_with_images = sum(1 for r in records if r.get("iiif_full_url"))
            f.write(f"Records with IIIF images: {records_with_images}\n")
            f.write(
                f"Image coverage: {(records_with_images / len(records) * 100):.1f}%\n\n"
            )

            for i, record in enumerate(records, 1):
                f.write(f"{i}. {record.get('title', 'No title')}\n")
                f.write(f"   Reference: {record.get('reference_number', 'Unknown')}\n")
                f.write(f"   Date: {record.get('date', 'Unknown')}\n")
                f.write(f"   Format: {record.get('format', 'Unknown')}\n")
                f.write(
                    f"   Description: {record.get('description', 'No description')[:100]}...\n"
                )

                if record.get("iiif_full_url"):
                    f.write(f"   Image URL: {record['iiif_full_url']}\n")
                else:
                    f.write("   Image URL: Not available\n")

                f.write("\n")

        print(f"Human-readable summary saved to {summary_file}")

    def save_csv(self, records, filename):
        """
        Save records to CSV format for easy viewing/importing
        """

        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "title",
                "reference_number",
                "date",
                "format",
                "description",
                "iiif_full_url",
                "iiif_thumbnail_url",
                "record_id",
                "ie_number",
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for record in records:
                row = {field: record.get(field, "") for field in fieldnames}
                # Truncate description for CSV
                if len(row["description"]) > 200:
                    row["description"] = row["description"][:200] + "..."
                writer.writerow(row)

        print(f"CSV export saved to {filename}")

    def fetch_all_records(
        self, collection_name, vid, max_records=2000, existing_refs=None
    ):
        """
        Fetch all records from a collection using pagination
        """
        if existing_refs is None:
            existing_refs = set()
        all_records = []
        limit = 50  # API limit per request
        offset = 0

        print(f"Fetching up to {max_records} records from '{collection_name}'...")
        print(f"Using pagination with {limit} records per request")

        while len(all_records) < max_records:
            print(f"\nFetching records {offset + 1}-{offset + limit}...")

            # Make API request
            api_response = self.search_collection(collection_name, vid, limit, offset)

            if not api_response:
                print("API request failed, stopping...")
                break

            # Extract records
            batch_records = self.extract_records(api_response, existing_refs)

            all_records.extend(batch_records)
            print(
                f"  Retrieved {len(batch_records)} new records (total new: {len(all_records)})"
            )

            if "docs" in api_response and len(api_response["docs"]) < limit:
                print("Reached end of collection")
                break

            offset += limit

            # Small delay between requests to be polite
            time.sleep(1)

        print(f"\n\u2713 Total new records fetched: {len(all_records)}")
        return all_records

    def create_download_script(self, records, script_name="download_images.sh"):
        """
        Create a bash script to download all images
        """
        records_with_images = [r for r in records if r.get("iiif_full_url")]

        script_content = f"""#!/bin/bash
# Download script for Carneal and Johnston Negative Collection
# Generated on {time.strftime("%Y-%m-%d %H:%M:%S")}
# Total images: {len(records_with_images)}

set -e  # Exit on any error

echo "Downloading {len(records_with_images)} images from Carneal and Johnston Collection..."
echo "Images will be saved to: carneal_johnston_images/"

mkdir -p carneal_johnston_images

"""

        for i, record in enumerate(records_with_images, 1):
            # Create safe filename
            title = record.get("title", "untitled")
            ref_num = record.get("reference_number", "").replace("C&J ", "CJ")
            safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title[:40])
            filename = (
                f"{ref_num}_{safe_title}.jpg"
                if ref_num
                else f"image_{i:03d}_{safe_title}.jpg"
            )

            script_content += f'''echo "Downloading {i}/{len(records_with_images)}: {title[:40]}..."
curl -s --fail -o "carneal_johnston_images/{filename}" "{record["iiif_full_url"]}" || echo "  Failed to download {filename}"

'''

        script_content += """echo "Download complete!"
echo "Images saved to: carneal_johnston_images/"
echo "Total files: $(ls carneal_johnston_images/ | wc -l)"
"""

        with open(script_name, "w") as f:
            f.write(script_content)

        # Make script executable
        os.chmod(script_name, 0o755)

        print(f"Download script created: {script_name}")
        print(f"Run with: ./{script_name}")
        return script_name


POLITE_WAIT_SECS = 1


def create_source_if_not_exist():
    """Get or create the Library of Virginia source"""
    source, created = Source.objects.get_or_create(
        name="Library of Virginia",
        defaults={
            "url": "https://www.lva.virginia.gov/",
            "description": "The Library of Virginia (LVA) is the state library and archives of Virginia. It is located in Richmond, Virginia and holds an extensive collection of books, manuscripts, maps, and photographs related to Virginia's history and culture.",
            "public": True,
        },
    )
    if created:
        print(f"Created source: {source.name}")
    else:
        print(f"Using existing source: {source.name}")
    return source


def create_collection_if_not_exist(source, collection_name, use_precollection=False):
    """Get or create a collection for the LVA Primo data"""
    collection_type = "pre-collection" if use_precollection else "collection"
    Model = PreCollection if use_precollection else Collection

    existing_collection = Model.objects.filter(
        source=source, name=collection_name
    ).first()

    if existing_collection:
        print(f"  ✓ Using existing {collection_type}: {existing_collection.name}")
        return existing_collection

    collection_url = f"https://lva.primo.exlibrisgroup.com/discovery/search?query=title,exact,{collection_name},AND&tab=LibraryCatalog&search_scope=MyInstitution&vid=01LVA_INST:01LVA&lang=en&offset=0"

    print(f"\n  {collection_type.title()} Details for '{collection_name}':")
    print(f"  Name: {collection_name}")
    print(f"  Source: {source.name}")
    print(f"  URL: {collection_url}")
    if use_precollection:
        print("  Type: Pre-collection (for review)")

    if input(f"\n  Create this {collection_type}? [y/N] ").strip().lower() == "y":
        collection = Model.objects.create(
            source=source,
            name=collection_name,
            url=collection_url,
            description=f"Collection from LVA Primo: {collection_name}",
        )
        print(f"Created {collection_type}: {collection.name}")
        return collection
    else:
        return None


def parse_date(date_str, default_edtf=None):
    """Parse date string and return EDTF"""
    if not date_str:
        return None

    if date_str.lower() == "no date":
        return default_edtf

    month_map = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    season_map = {
        "spring": 21,
        "summer": 22,
        "autumn": 23,
        "fall": 23,
        "winter": 24,
    }

    date_str = date_str.strip()

    if date_str == "ca. early 1920s":
        return "[1920..1925]"

    if date_str == "ca. 1921 or 1922":
        return "[1921,1922]"

    # YYYY
    year_match = re.match(r"^(\d{4})$", date_str)
    if year_match:
        return year_match.group(1)

    # YYYY-MM-DD
    full_date_match = re.match(r"^(\d{4}-\d{2}-\d{2})$", date_str)
    if full_date_match:
        return full_date_match.group(1)

    # Circa YYYY
    circa_match = re.match(r"(?i)(?:circa|ca?\.)\s+(\d{4})$", date_str)
    if circa_match:
        return circa_match.group(1) + "~"

    # Circa YYYY?
    circa_match = re.match(r"(?i)(?:circa|ca?\.)\s+(\d{4})\?$", date_str)
    if circa_match:
        return circa_match.group(1) + "?"

    # Handle "ca. YYYY-YYYY" format
    circa_year_range_match = re.match(
        r"(?i)(?:circa|ca?\.)\s+(\d{4})-(\d{4})$", date_str
    )
    if circa_year_range_match:
        first_year = int(circa_year_range_match.group(1))
        second_year = int(circa_year_range_match.group(2))
        if second_year == (first_year + 1):
            return (
                f"[{first_year},{second_year}]"  # trailing tilde is not EDTF compliant?
            )
        else:
            return f"[{first_year}..{second_year}]"  # trailing tilde is not EDTF compliant?

    # Handle "ca. YYYY or YYYY" format
    circa_year_range_match = re.match(
        r"(?i)(?:circa|ca?\.)\s+(\d{4})\s+or\s+(\d{4})$", date_str
    )
    if circa_year_range_match:
        first_year = int(circa_year_range_match.group(1))
        second_year = int(circa_year_range_match.group(2))
        if second_year == (first_year + 1):
            return (
                f"[{first_year},{second_year}]"  # trailing tilde is not EDTF compliant?
            )
        else:
            return f"[{first_year}..{second_year}]"  # trailing tilde is not EDTF compliant?

    # YYYY-YYYY
    year_range_match = re.match(r"^(\d{4})-(\d{4})$", date_str)
    if year_range_match:
        first_year = int(year_range_match.group(1))
        second_year = int(year_range_match.group(2))
        if second_year == (first_year + 1):
            return f"[{first_year},{second_year}]"
        else:
            return f"[{first_year}..{second_year}]"

    # Try "MM/YYYY" format
    month_year_match = re.match(r"^(\d{1,2})/(\d{4})$", date_str)
    if month_year_match:
        return month_year_match.group(2) + "-" + month_year_match.group(1).zfill(2)

    month_day_year_match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_str)
    if month_day_year_match:
        # BE CAREFUL! Take note of different order in EDTF
        return (
            month_day_year_match.group(3)
            + "-"
            + month_day_year_match.group(1).zfill(2)
            + "-"
            + month_day_year_match.group(2).zfill(2)
        )

    # Try "Month YYYY" format (e.g., "June 1993")
    month_name_year_match = re.match(r"^(\w+)\s+(\d{4})$", date_str)
    if month_name_year_match:
        month_name = month_name_year_match.group(1).lower()
        if month_name in month_map:
            return (
                month_name_year_match.group(2)
                + "-"
                + str(month_map[month_name]).zfill(2)
            )

    # Try "Month Day, YYYY" format (e.g., "June 13, 1993")
    month_name_day_year_match = re.match(
        r"^(\w+)\s+(\d{1,2})(?:,)?\s+(\d{4})$", date_str
    )
    if month_name_day_year_match:
        month_name = month_name_day_year_match.group(1).lower()
        if month_name in month_map:
            # BE CAREFUL! Take note of different order in EDTF
            return (
                month_name_day_year_match.group(3)
                + "-"
                + str(month_map[month_name]).zfill(2)
                + "-"
                + month_name_day_year_match.group(2).zfill(2)
            )

    # Try Season YYYY
    season_year_match = re.match(r"^(\w+)\s+(\d{4})$", date_str)
    if season_year_match:
        season_name = season_year_match.group(1).lower()
        if season_name in season_map:
            return season_year_match.group(2) + "-" + str(season_map[season_name])

    # If no matches found, breakpoint for debugging
    print(f"No date found for '{date_str}'!")
    breakpoint()


def add_arguments(parser):
    """Add lva_primo_search-specific arguments to the parser."""
    parser.add_argument("collection_name", type=str)
    parser.add_argument(
        "--vid", required=True, help="View ID (e.g., '01LVA_INST:01LVA')"
    )
    parser.add_argument(
        "--max-records", type=int, default=2000, help="Maximum records to fetch"
    )
    parser.add_argument(
        "--hotlink",
        action="store_true",
        help="Hotlink images instead of uploading to R2",
    )
    parser.add_argument(
        "--default-edtf", help="EDTF date to use when 'no date' is found."
    )


def handle(options):
    """Run the LVA Primo search import."""
    collection_name = options["collection_name"]
    vid = options["vid"]
    max_records = options["max_records"]
    hotlink = options["hotlink"]
    default_edtf = options["default_edtf"]

    source = create_source_if_not_exist()
    collection = create_collection_if_not_exist(
        source, collection_name, use_precollection=hotlink
    )

    if not collection:
        print("No collection created, exiting.")
        return

    Model = PreImage if hotlink else Image
    print("Fetching existing image references from database...")
    existing_refs = set(Model.objects.values_list("ref", flat=True))
    print(f"Found {len(existing_refs)} existing references to skip.")

    client = PrimoAPIClient()
    records = client.fetch_all_records(
        collection_name, vid, max_records, existing_refs=existing_refs
    )

    if not records:
        print("No new records to import, exiting.")
        return

    r2_uploader = R2Uploader()

    for record in tqdm(records, desc="Saving new images"):
        ref = record.get("reference_number") or record.get("record_id")
        if not ref:
            tqdm.write("      \u2717 No reference or record ID found, skipping")
            continue

        if "iiif_full_url" not in record or not record["iiif_full_url"]:
            tqdm.write("      \u2717 No image URL found for record, skipping")
            continue

        permalink = record["iiif_full_url"]
        if not hotlink:
            permalink = r2_uploader.upload_url(
                permalink, in_tqdm=True, raise_on_err=False
            )

        if permalink is None:
            tqdm.write("      \u2717 Unable to download image, skipping")
            continue

        try:
            tqdm.write(f"      → Inserting image {record.get('title')}")
            edtf_date = parse_date(record.get("date"), default_edtf)

            if hotlink:
                image = PreImage.objects.create(
                    collection=collection,
                    title=record.get("title", "No title"),
                    permalink=permalink,
                    ref=ref,
                    description=record.get("description", ""),
                    creator=record.get("creator", ""),
                    original_date=record.get("date"),
                    edtf_date=edtf_date,
                    license=options.get("license"),
                )
                tqdm.write(f"      → Created pre-image ID: {image.id}")
            else:
                image = Image.objects.create(
                    collection=collection,
                    title=record.get("title", "No title"),
                    permalink=permalink,
                    ref=ref,
                    original_url=f"https://lva.primo.exlibrisgroup.com/discovery/fulldisplay?docid={record.get('record_id')}&context=L&vid={vid}",
                    description=record.get("description", ""),
                    creator=record.get("creator", ""),
                    original_date=record.get("date"),
                    edtf_date=edtf_date,
                    license=options.get("license"),
                )
                tqdm.write(f"      → Created image ID: {image.id}")
        except Exception as e:
            tqdm.write(f"      \u2717 Error creating image: {e}")

        sleep(POLITE_WAIT_SECS)
