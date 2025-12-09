#!/usr/bin/env python3
"""
LVA Primo Collection Scraper (by Collection ID) - SIMPLIFIED VERSION

Usage:
    uv run scripts/importers/lva_primo_collection_by_id.py "Collection Name" --collection-id 81106146120005756 --vid 01LVA_INST:01LVA
"""

import os
import re
import sys
from time import sleep

import click
from tqdm import tqdm

# Add the Django project to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(script_dir, "..", "..")
sys.path.insert(0, project_root)

# Change to project directory for Django
os.chdir(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "georeference_tool.settings")

import django

django.setup()

import csv
import json
import time

import requests

from images.models import Collection, Image, PreCollection, PreImage, Source


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

    def get_session_token(self, url):
        """
        Get a valid Bearer token by loading the page first
        """
        print("Getting session token...")

        try:
            # Load the page to establish session
            response = self.session.get(url)
            response.raise_for_status()

            print(f"Page loaded successfully (status {response.status_code}, length {len(response.text)})")

            # Look for bearer token in the page JavaScript
            token_patterns = [
                r"Bearer\s+([A-Za-z0-9\-_\.]+)",
                r'authorization["\']:\s*["\']Bearer\s+([A-Za-z0-9\-_\.]+)["\']',
                r'token["\']:\s*["\']([A-Za-z0-9\-_\.]+)["\']',
                r'jwt["\']\s*:\s*["\']([A-Za-z0-9\-_\.]+)["\']',
                r'apiKey["\']\s*:\s*["\']([A-Za-z0-9\-_\.]+)["\']',
            ]

            for pattern in token_patterns:
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                if matches:
                    token = matches[0]
                    if len(token) > 50:  # JWT tokens are typically long
                        self.bearer_token = token
                        print(f"Found Bearer token: {token[:20]}...")
                        return True

            # Also check for any X-CSRF-TOKEN that might be needed
            csrf_pattern = r'X-CSRF-TOKEN["\']:\s*["\']([A-Za-z0-9\-_\.]+)["\']'
            csrf_matches = re.findall(csrf_pattern, response.text, re.IGNORECASE)
            if csrf_matches:
                csrf_token = csrf_matches[0]
                self.session.headers.update({"X-CSRF-TOKEN": csrf_token})
                print(f"Added X-CSRF-TOKEN to session headers: {csrf_token[:10]}...")

            # Save cookies from the response
            if response.cookies:
                print(f"Got {len(response.cookies)} cookies from page")

            # Save the page for inspection if needed
            with open("collection_page.html", "w", encoding="utf-8") as f:
                f.write(response.text)
                print("Saved page HTML to collection_page.html for inspection")

            if not self.bearer_token:
                print("No Bearer token found in page source")
                return False

            return True

        except requests.RequestException as e:
            print(f"Error getting session: {e}")
            return False

    def fetch_collection_by_id(self, collection_id, vid, limit=10, offset=0):
        """
        Fetch items from a specific collection by its ID
        """
        # Use the pnxs endpoint with cdparentid query
        collection_api_url = f"{self.base_url}/primaws/rest/pub/pnxs"

        # Build query parameters for collection ID
        query_params = {
            "acTriggered": "false",
            "disableCache": "false",
            "getMore": "0",
            "inst": vid.split(":")[0],  # Extract institution from vid
            "isCDSearch": "true",
            "lang": "en",
            "limit": str(limit),
            "newspapersActive": "true",
            "newspapersSearch": "false",
            "offset": str(offset),
            "q": f"cdparentid,exact,{collection_id}",
            "qExclude": "",
            "qInclude": "",
            "refEntryActive": "false",
            "rtaLinks": "true",
            "scope": "browse_search",
            "skipDelivery": "Y",
            "sort": "title",
            "tab": "LibraryCatalog",
            "vid": vid,
        }

        # First, get a session token from the collection URL
        collection_url = f"{self.base_url}/discovery/collectionDiscovery?vid={vid}&inst={vid.split(':')[0]}&collectionId={collection_id}"
        print(f"Trying to access collection URL: {collection_url}")

        # Get a bearer token first to use with our API calls
        self.get_session_token(collection_url)

        try:
            # Make the API request
            print(f"Making request to API endpoint: {collection_api_url}")
            print(f"With parameters: {query_params}")

            headers = {}
            if self.bearer_token:
                headers["Authorization"] = f"Bearer {self.bearer_token}"

            response = self.session.get(collection_api_url, params=query_params, headers=headers)
            print(f"API response status: {response.status_code}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    return data
                except json.JSONDecodeError:
                    print("Response is not valid JSON")
                    print(f"Response content: {response.text[:500]}")
            else:
                print(f"API request failed: {response.status_code}")
                print(f"Response content: {response.text[:500]}")

        except requests.RequestException as e:
            print(f"Error making API request: {e}")

        return None

    def get_edelivery_url(self, record_id, vid="01LVA_INST:01LVA"):
        """
        Get delivery URL for a specific record using the edelivery API
        """
        if not record_id:
            return None

        edelivery_url = f"{self.base_url}/primaws/rest/pub/edelivery/{record_id}"

        print(f"Requesting edelivery data for {record_id}...")
        headers = {
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json, text/plain, */*",
        }

        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        try:
            response = self.session.post(
                edelivery_url,
                headers=headers,
                params={"vid": vid, "lang": "en", "googleScholar": "false"},
                json={"sharedDigitalCandidates": None},
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()

                # Check for electronic services with URLs
                if "electronicServices" in data and data["electronicServices"]:
                    for service in data["electronicServices"]:
                        if "serviceUrl" in service and service["serviceUrl"]:
                            url = service["serviceUrl"]
                            print(f"Found service URL: {url}")

                            # Extract IE number from URL
                            ie_match = re.search(r"dps_pid=IE(\d+)", url)
                            if ie_match:
                                ie_number = ie_match.group(1)
                                print(f"Extracted IE number: {ie_number}")
                                return {"url": url, "ie_number": ie_number}

                # Check GetIt1 links as fallback
                if "GetIt1" in data and data["GetIt1"]:
                    for getit in data["GetIt1"]:
                        if "links" in getit and getit["links"]:
                            for link_data in getit["links"]:
                                if "link" in link_data:
                                    url = link_data["link"]
                                    print(f"Found GetIt1 link: {url}")

                                    # Extract IE number from URL
                                    ie_match = re.search(r"dps_pid=IE(\d+)", url)
                                    if ie_match:
                                        ie_number = ie_match.group(1)
                                        print(f"Extracted IE number: {ie_number}")
                                        return {"url": url, "ie_number": ie_number}
            else:
                print(f"Edelivery API request failed: {response.status_code}")
                print(f"Response: {response.text[:500]}")

        except (requests.RequestException, json.JSONDecodeError) as e:
            print(f"Error accessing edelivery API: {e}")

        return None

    def get_image_url_from_record(self, record):
        """
        Get image URL from record using edelivery API + IIIF manifest
        """
        record_id = record.get("record_id", "")

        if not record_id:
            return None

        # Try using edelivery API to get IE number
        edelivery_info = self.get_edelivery_url(record_id)
        if not edelivery_info or "ie_number" not in edelivery_info:
            return None

        ie_number = edelivery_info["ie_number"]
        record["ie_number"] = ie_number

        # Get the IIIF manifest URL for this IE number
        manifest_url = f"https://rosetta.virginiamemory.com/delivery/iiif/presentation/2.1/IE{ie_number}/manifest"

        try:
            with requests.Session() as session:
                session.headers.update(
                    {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                    }
                )

                # Fetch and parse the manifest
                response = session.get(manifest_url, timeout=15)
                response.raise_for_status()

                manifest = response.json()
                iiif_url = self.extract_image_from_manifest(manifest)

                if iiif_url:
                    return iiif_url

                return None

        except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"  ✗ Error fetching manifest for IE{ie_number}: {e}")
            return None

    def extract_image_from_manifest(self, manifest):
        """
        Extract image URL from IIIF manifest
        """
        try:
            # Check for IIIF 2.0 style manifest
            if "sequences" in manifest and len(manifest["sequences"]) > 0:
                sequence = manifest["sequences"][0]
                if "canvases" in sequence and len(sequence["canvases"]) > 0:
                    canvas = sequence["canvases"][0]
                    if "images" in canvas and len(canvas["images"]) > 0:
                        image = canvas["images"][0]

                        # Some manifests include direct URLs to images
                        if "resource" in image:
                            resource = image["resource"]

                            # Check if the resource itself is a direct URL
                            if isinstance(resource, str) and resource.endswith(".jpg"):
                                return resource

                            # Check for @id in resource
                            if "@id" in resource:
                                image_url = resource["@id"]

                                # Check if it's already a full image URL
                                if image_url.endswith(".jpg"):
                                    return image_url

                                # Check if it's an image info URL
                                if "/info.json" in image_url:
                                    # Convert info URL to image URL
                                    image_url = image_url.replace("/info.json", "")
                                    return f"{image_url}/full/max/0/default.jpg"

                                # Try to get image info
                                try:
                                    with requests.Session() as session:
                                        info_response = session.get(image_url, timeout=15)
                                        if info_response.status_code == 200:
                                            try:
                                                image_info = info_response.json()
                                                if "service" in image_info and "@id" in image_info["service"]:
                                                    service_id = image_info["service"]["@id"]
                                                    return f"{service_id}/full/max/0/default.jpg"
                                            except json.JSONDecodeError:
                                                # If it's not JSON but a direct image, return the URL
                                                if 'image/' in info_response.headers.get('Content-Type', ''):
                                                    return image_url
                                except Exception as e:
                                    print(f"Error fetching image info: {e}")

            # Check for IIIF 3.0 style manifest
            if "items" in manifest:
                for item in manifest["items"]:
                    if "items" in item:
                        for annotation_page in item["items"]:
                            if "items" in annotation_page:
                                for annotation in annotation_page["items"]:
                                    if "body" in annotation and "id" in annotation["body"]:
                                        return annotation["body"]["id"]

            # Check for any image URLs in the manifest
            manifest_str = json.dumps(manifest)
            jpg_urls = re.findall(r'https?://[^\s"]+\.jpg', manifest_str)
            for url in jpg_urls:
                if "/full/max/" in url or "/full/full/" in url:
                    return url

        except (KeyError, IndexError) as e:
            print(f"Error extracting image from manifest: {e}")

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
        elif "items" in api_response:
            # Collection-specific response structure
            docs = api_response["items"]
        elif "records" in api_response:
            # Another possible collection structure
            docs = api_response["records"]
        elif "collection" in api_response and "items" in api_response["collection"]:
            # Structure extracted from initial state
            docs = api_response["collection"]["items"]
        else:
            # Log the full response structure to diagnose the issue
            print("Unknown response structure, examining keys:")
            print(f"Top-level keys: {list(api_response.keys())}")
            for key, value in api_response.items():
                if isinstance(value, dict):
                    print(f"  {key} keys: {list(value.keys())}")
                elif isinstance(value, list) and len(value) > 0:
                    print(f"  {key} is a list with {len(value)} items")
                    if isinstance(value[0], dict):
                        print(f"    First item keys: {list(value[0].keys())}")

            # Save the full response for debugging
            with open("collection_response.json", "w", encoding="utf-8") as f:
                json.dump(api_response, f, indent=2)
            print("Full response saved to collection_response.json")
            return []

        # Save the first record for debugging purposes
        if docs and len(docs) > 0:
            with open("example_record.json", "w", encoding="utf-8") as f:
                json.dump(docs[0], f, indent=2)
            print("Saved first record to example_record.json for reference")

            # Debug first record structure
            first_doc = docs[0]
            print(f"\nFirst record keys: {list(first_doc.keys())}")
            if "pnx" in first_doc:
                pnx = first_doc["pnx"]
                print(f"PNX keys: {list(pnx.keys())}")
                if "links" in pnx:
                    print(f"Links keys: {list(pnx['links'].keys())}")

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

                # Links section might contain thumbnail and IIIF info
                if "links" in pnx:
                    links = pnx["links"]

                    # Check for thumbnail URL
                    if "thumbnail" in links and links["thumbnail"]:
                        thumbnail_url = links["thumbnail"][0]
                        # Some collections use different URL patterns
                        if "virginiamemory.com" in thumbnail_url:
                            # This is likely a IIIF URL we can derive the full size from
                            record["iiif_thumbnail_url"] = thumbnail_url
                            # Replace thumbnail parameters with full size
                            if "/full/150," in thumbnail_url:
                                record["iiif_full_url"] = thumbnail_url.replace("/full/150,", "/full/max/")
                                record["iiif_medium_url"] = thumbnail_url.replace("/full/150,", "/full/800,/")
                            elif "/full/small" in thumbnail_url:
                                record["iiif_full_url"] = thumbnail_url.replace("/full/small", "/full/max")
                                record["iiif_medium_url"] = thumbnail_url.replace("/full/small", "/full/800,")

                    # Check for linktorsrc which might contain IIIF manifest links
                    if "linktorsrc" in links and links["linktorsrc"]:
                        for link in links["linktorsrc"]:
                            if "virginiamemory.com" in link and "manifest" in link:
                                # This is a IIIF manifest URL
                                record["manifest_url"] = link
                                # Try to extract the IE number if we don't have it yet
                                if not record["ie_number"]:
                                    ie_match = re.search(r"IE(\d+)/manifest", link)
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

                # If thumbnailForCD has hasD=true, this indicates there's digital content
                if "thumbnailForCD" in doc and doc["thumbnailForCD"].get("hasD") == True:
                    record["has_digital_content"] = True

                # If we don't have image URLs, try to get them using our LVA-specific method
                if not record.get("iiif_full_url"):
                    print(f"Finding image URL for record {record.get('title')[:30]}...")
                    image_url = self.get_image_url_from_record(record)
                    if image_url:
                        # Check if the URL is a IIIF presentation URL
                        if "/delivery/iiif/presentation/" in image_url:
                            print(f"  ⚠ Found IIIF presentation URL, extracting actual image URL...")
                            try:
                                # Use the session from the class
                                with self.session as session:
                                    response = session.get(image_url, timeout=15)
                                    if response.status_code == 200:
                                        try:
                                            data = response.json()
                                            if "service" in data and "@id" in data["service"]:
                                                image_url = f"{data['service']['@id']}/full/max/0/default.jpg"
                                                print(f"  ✓ Extracted actual image URL from IIIF metadata: {image_url[:60]}...")
                                        except json.JSONDecodeError:
                                            print(f"  ✗ Failed to parse IIIF metadata as JSON")
                                            continue
                            except Exception as e:
                                print(f"  ✗ Error accessing IIIF presentation URL: {e}")
                                continue

                        # Verify this is an actual image URL by checking headers
                        try:
                            # Use the session from the class
                            with self.session as session:
                                headers_response = session.head(image_url, timeout=10)
                                content_type = headers_response.headers.get('Content-Type', '')

                                if 'application/json' in content_type:
                                    print(f"  ⚠ URL returns JSON metadata instead of an image: {image_url[:60]}...")
                                    # Try to extract actual image URL from JSON
                                    try:
                                        json_response = session.get(image_url, timeout=10)
                                        data = json_response.json()
                                        if "service" in data and "@id" in data["service"]:
                                            image_url = f"{data['service']['@id']}/full/max/0/default.jpg"
                                            print(f"  ✓ Extracted actual image URL from JSON: {image_url[:60]}...")
                                    except Exception as e:
                                        print(f"  ✗ Failed to extract image URL from JSON: {e}")
                                        continue
                                elif 'image/' not in content_type:
                                    print(f"  ⚠ URL does not return an image ({content_type}): {image_url[:60]}...")
                                    continue
                        except Exception as e:
                            print(f"  ⚠ Could not verify image URL: {e}")

                        record["iiif_full_url"] = image_url
                        record["iiif_thumbnail_url"] = image_url.replace(
                            "/full/max/", "/full/300,/"
                        ).replace(
                            "/full/full/", "/full/300,/"
                        )
                        record["iiif_medium_url"] = image_url.replace(
                            "/full/max/", "/full/800,/"
                        ).replace(
                            "/full/full/", "/full/800,/"
                        )
                        print(f"  ✓ Found image URL: {image_url[:60]}...")
                    else:
                        print(f"  ✗ Could not find image URL")
                        record["iiif_full_url"] = ""
                        record["iiif_thumbnail_url"] = ""
                        record["iiif_medium_url"] = ""

                # Add full PNX for detailed analysis
                record["full_pnx"] = pnx

            # Extract delivery information (might contain access URLs)
            if "delivery" in doc:
                record["delivery"] = doc["delivery"]

                # Check if delivery contains thumbnail URL
                if not record.get("iiif_thumbnail_url") and "almagetit" in record["delivery"]:
                    alma_data = record["delivery"]["almagetit"]
                    if alma_data and "thumbnail_url" in alma_data:
                        thumbnail_url = alma_data["thumbnail_url"]
                        record["iiif_thumbnail_url"] = thumbnail_url
                        # Attempt to convert to full size URL if it's IIIF
                        if "virginiamemory.com" in thumbnail_url and "/full/" in thumbnail_url:
                            record["iiif_full_url"] = re.sub(r"/full/\d+,/", "/full/max/", thumbnail_url)
                            record["iiif_medium_url"] = re.sub(r"/full/\d+,/", "/full/800,/", thumbnail_url)

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
                    print(f"  ✓ {i + 1}. {title} - WORKING")
                    working_count += 1
                else:
                    print(
                        f"  ✗ {i + 1}. {title} - FAILED ({response.status_code})"
                    )
            except Exception as e:
                print(f"  ✗ {i + 1}. {title} - ERROR ({e})")

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

    def fetch_all_records_by_collection_id(
        self, collection_id, collection_name, vid, max_records=2000, existing_refs=None
    ):
        """
        Fetch all records from a collection using its ID and pagination
        """
        if existing_refs is None:
            existing_refs = set()
        all_records = []
        limit = 20  # API limit per request - this is what the browser uses
        offset = 0

        print(f"Fetching up to {max_records} records from collection ID: '{collection_id}'...")
        print(f"Using pagination with {limit} records per request")

        # First attempt - get initial batch of records
        print(f"\nFetching initial records...")
        api_response = self.fetch_collection_by_id(collection_id, vid, limit, offset)

        if not api_response:
            print("Initial API request failed, stopping...")
            return []

        # Some debugging info about the response structure
        if "docs" in api_response:
            print(f"Found {len(api_response['docs'])} items in 'docs' field")
            print(f"Total items in collection: {api_response.get('info', {}).get('total', 'unknown')}")
        else:
            print("Response structure:")
            for key in api_response.keys():
                print(f"  - {key}")
                if isinstance(api_response[key], dict):
                    for subkey in api_response[key].keys():
                        print(f"    - {subkey}")

        # Continue with pagination
        while len(all_records) < max_records:
            # Extract records
            batch_records = self.extract_records(api_response, existing_refs)

            all_records.extend(batch_records)
            print(
                f"  Retrieved {len(batch_records)} new records (total new: {len(all_records)})"
            )

            if "docs" in api_response and len(api_response["docs"]) < limit:
                print("Reached end of collection")
                break

            # Move to next page
            offset += limit
            print(f"\nFetching records {offset + 1}-{offset + limit}...")
            api_response = self.fetch_collection_by_id(collection_id, vid, limit, offset)

            if not api_response:
                print("API request failed, stopping pagination...")
                break

            # Small delay between requests to be polite
            time.sleep(1)

        print(f"\n✓ Total new records fetched: {len(all_records)}")
        return all_records

    def create_download_script(self, records, script_name="download_images.sh"):
        """
        Create a bash script to download all images
        """
        records_with_images = [r for r in records if r.get("iiif_full_url")]

        print(f"\nFound {len(records_with_images)} records with image URLs out of {len(records)} total records")
        if len(records_with_images) == 0:
            print("No images found in any records!")

            # Debug the first few records to see why we're missing images
            print("\nDebugging first 5 records to check for image URL issues:")
            for i, record in enumerate(records[:5]):
                print(f"\nRecord {i+1}: {record.get('title', 'No title')[:40]}")
                print(f"  Record ID: {record.get('record_id', 'None')}")
                print(f"  IE number: {record.get('ie_number', 'None')}")
                print(f"  Reference number: {record.get('reference_number', 'None')}")

                # Check for identifiers that might contain IE numbers
                if 'identifiers' in record:
                    print(f"  Identifiers: {record['identifiers']}")

                # Check if there are links in PNX that might contain images
                if 'full_pnx' in record and 'links' in record['full_pnx']:
                    links = record['full_pnx']['links']
                    print(f"  PNX links: {list(links.keys())}")
                    if 'thumbnail' in links:
                        print(f"  Thumbnail: {links['thumbnail']}")

                # Check delivery data
                if 'delivery' in record:
                    print(f"  Delivery keys: {list(record['delivery'].keys())}")
                    if 'almagetit' in record['delivery']:
                        alma = record['delivery']['almagetit']
                        if isinstance(alma, dict) and 'thumbnail_url' in alma:
                            print(f"  Alma thumbnail: {alma['thumbnail_url']}")

        script_content = f"""#!/bin/bash
# Download script for LVA Collection images
# Generated on {time.strftime("%Y-%m-%d %H:%M:%S")}
# Total images: {len(records_with_images)}

set -e  # Exit on any error

echo "Downloading {len(records_with_images)} images..."
echo "Images will be saved to: lva_collection_images/"

mkdir -p lva_collection_images

"""

        for i, record in enumerate(records_with_images, 1):
            # Create safe filename
            title = record.get("title", "untitled")
            ref_num = record.get("reference_number", "").replace("C&J ", "CJ")
            if not ref_num:
                ref_num = record.get("record_id", "")
            safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title[:40])
            filename = (
                f"{ref_num}_{safe_title}.jpg"
                if ref_num
                else f"image_{i:03d}_{safe_title}.jpg"
            )

            script_content += f'''echo "Downloading {i}/{len(records_with_images)}: {title[:40]}..."
curl -s --fail -o "lva_collection_images/{filename}" "{record["iiif_full_url"]}" || echo "  Failed to download {filename}"

'''

        script_content += """echo "Download complete!"
echo "Images saved to: lva_collection_images/"
echo "Total files: $(ls lva_collection_images/ | wc -l)"
"""

        with open(script_name, "w") as f:
            f.write(script_content)

        # Make script executable
        os.chmod(script_name, 0o755)

        print(f"Download script created: {script_name}")
        print(f"Run with: ./{script_name}")
        return script_name


# Import R2 uploader from the same directory
try:
    from r2_uploader import R2Uploader
except ImportError:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    from r2_uploader import R2Uploader

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


def create_collection_if_not_exist(source, collection_name, collection_id, vid, use_precollection=False):
    """Get or create a collection for the LVA Primo data"""
    collection_type = "pre-collection" if use_precollection else "collection"
    Model = PreCollection if use_precollection else Collection

    existing_collection = Model.objects.filter(
        source=source, name=collection_name
    ).first()

    if existing_collection:
        print(f"  ✓ Using existing {collection_type}: {existing_collection.name}")
        return existing_collection

    collection_url = f"https://lva.primo.exlibrisgroup.com/discovery/collectionDiscovery?vid={vid}&inst={vid.split(':')[0]}&collectionId={collection_id}"

    print(f"\n  {collection_type.title()} Details for '{collection_name}':")
    print(f"  Name: {collection_name}")
    print(f"  Source: {source.name}")
    print(f"  URL: {collection_url}")
    if use_precollection:
        print("  Type: Pre-collection (for review)")

    if click.confirm(f"\n  Create this {collection_type}?"):
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


def parse_date(date_str, default_edtf=None, min_year=None, max_year=None):
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

    # Handle "YYYY--" and "YYYY--?" formats (incomplete dates)
    incomplete_date_match = re.match(r"^(\d{4})-{2}(\?)?$", date_str)
    if incomplete_date_match and min_year is not None and max_year is not None:
        year = incomplete_date_match.group(1)
        return f"[{year}..{max_year}]"

    # Handle "YY--" and "YY--?" formats (incomplete 2-digit century dates like "19--?")
    incomplete_century_match = re.match(r"^(\d{2})-{2}(\?)?$", date_str)
    if incomplete_century_match and min_year is not None and max_year is not None:
        century_prefix = incomplete_century_match.group(1)
        # Convert "19" to year range 1900-1999
        start_year = int(century_prefix) * 100
        end_year = start_year + 99
        # Clamp to the provided min/max years
        start_year = max(start_year, min_year)
        end_year = min(end_year, max_year)
        return f"[{start_year}..{end_year}]"

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

    # If no matches found, raise an error
    raise ValueError(f"Unable to parse date: '{date_str}'")


@click.command()
@click.argument("collection_name")
@click.option("--collection-id", required=True, help="Collection ID (e.g., '81106146120005756')")
@click.option("--vid", required=True, help="View ID (e.g., '01LVA_INST:01LVA')")
@click.option("--min-year", type=int, required=True, help="Minimum year for incomplete dates (e.g., 1900)")
@click.option("--max-year", type=int, required=True, help="Maximum year for incomplete dates (e.g., 1950)")
@click.option("--max-records", type=int, default=2000, help="Maximum records to fetch")
@click.option(
    "--hotlink", is_flag=True, help="Hotlink images instead of uploading to R2"
)
@click.option("--default-edtf", help="EDTF date to use when 'no date' is found.")
@click.option(
    "--debug", is_flag=True, help="Enable additional debugging output"
)
@click.option(
    "--skip-missing-images", is_flag=True, help="Skip records without image URLs (otherwise fail)"
)
@click.option(
    "--save-json", is_flag=True, help="Save all records to JSON file for debugging"
)
def main(collection_name, collection_id, vid, min_year, max_year, max_records, hotlink, default_edtf, debug, skip_missing_images, save_json):
    """Scrape records from LVA Primo collection by ID and import into Django."""
    source = create_source_if_not_exist()

    # Display collection URL for reference
    collection_url = f"https://lva.primo.exlibrisgroup.com/discovery/collectionDiscovery?vid={vid}&inst={vid.split(':')[0]}&collectionId={collection_id}"
    print(f"\nCollection URL: {collection_url}")

    # Display API URL for reference
    api_url = f"https://lva.primo.exlibrisgroup.com/primaws/rest/pub/pnxs?q=cdparentid,exact,{collection_id}&vid={vid}"
    print(f"API URL: {api_url}")
    print("Please verify this collection is accessible in your browser before proceeding.")

    if debug:
        # Try to access the URL directly to validate it
        try:
            import requests
            print("\nValidating collection URL...")
            response = requests.get(collection_url)
            print(f"Status code: {response.status_code}")
            if response.status_code == 200:
                print("✓ Collection URL is accessible")
            else:
                print(f"⚠ Warning: Collection URL returned status {response.status_code}")
        except Exception as e:
            print(f"⚠ Warning: Error validating collection URL: {e}")

    collection = create_collection_if_not_exist(
        source, collection_name, collection_id, vid, use_precollection=hotlink
    )

    if not collection:
        print("No collection created, exiting.")
        return

    Model = PreImage if hotlink else Image
    print("Fetching existing image references from database...")
    existing_refs = set(Model.objects.values_list("ref", flat=True))
    print(f"Found {len(existing_refs)} existing references to skip.")

    client = PrimoAPIClient()

    # Try to get a bearer token for the edelivery API
    collection_url = f"https://lva.primo.exlibrisgroup.com/discovery/collectionDiscovery?vid={vid}&inst={vid.split(':')[0]}&collectionId={collection_id}"
    print("Getting session token for edelivery API...")
    client.get_session_token(collection_url)

    records = client.fetch_all_records_by_collection_id(
        collection_id, collection_name, vid, max_records, existing_refs=existing_refs
    )

    if not records:
        print("\n⚠ No records retrieved. Possible issues:")
        print("  - The collection ID might be incorrect")
        print("  - The collection might be empty")
        print("  - The API might require authentication")
        print("\nTry accessing the collection URL in a browser and check the network tab")
        print(f"to see what API calls are made: {collection_url}")
        print("\nThe correct API call should be:")
        print(f"curl '{api_url}&limit=20&offset=0'")
        return

    # Count records with images
    records_with_images = [r for r in records if r.get("iiif_full_url")]
    print(f"\nFound {len(records_with_images)} records with image URLs out of {len(records)} total records")

    if len(records_with_images) == 0:
        print("\n⚠ No images found in any records! This collection might not have accessible IIIF images.")
        print("Possible causes:")
        print("  - Images may require authentication")
        print("  - Images may use a different access method")
        print("  - Collection might not have digitized images")

        if save_json:
            json_file = f"collection_{collection_id}_records.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
            print(f"Saved all records to {json_file} for analysis")

        if not skip_missing_images:
            print("\nUse --skip-missing-images to proceed anyway.")
            return
        else:
            print("\nProceeding with import (no images will be imported)")

    r2_uploader = R2Uploader()

    for record in tqdm(records, desc="Saving new images"):
        ref = record.get("reference_number") or record.get("record_id")
        if not ref:
            tqdm.write("      ✗ No reference or record ID found, skipping")
            continue

        if "iiif_full_url" not in record or not record["iiif_full_url"]:
            if skip_missing_images:
                tqdm.write(f"      ✗ No image URL found for {record.get('title')[:30]}..., importing metadata only")
                permalink = "" # Empty permalink, will create record without image
            else:
                tqdm.write("      ✗ No image URL found for record, skipping")
                continue
        else:
            permalink = record["iiif_full_url"]

            # Only upload to R2 if we have a valid URL
            if not hotlink and permalink:
                # Verify this is an actual image before uploading
                try:
                    # Use a new session for verification
                    with requests.Session() as session:
                        session.headers.update({"User-Agent": "Mozilla/5.0"})

                        # First check if it's a IIIF presentation URL
                        if "/delivery/iiif/presentation/" in permalink:
                            response = session.get(permalink, timeout=10)
                            try:
                                data = response.json()
                                if "service" in data and "@id" in data["service"]:
                                    permalink = f"{data['service']['@id']}/full/max/0/default.jpg"
                            except Exception:
                                pass

                        # Verify the content type of our URL
                        response = session.head(permalink, timeout=10)
                        content_type = response.headers.get('Content-Type', '')

                        if 'application/json' in content_type:
                            try:
                                json_response = session.get(permalink, timeout=10)
                                data = json_response.json()
                                if "service" in data and "@id" in data["service"]:
                                    permalink = f"{data['service']['@id']}/full/max/0/default.jpg"
                            except Exception:
                                pass
                except Exception:
                    pass

                # Final check for proper URL format
                if "virginiamemory.com" in permalink:
                    if "iiif/presentation" in permalink or "delivery/iiif/presentation" in permalink:
                        # Extract IE and FL numbers if possible
                        ie_match = re.search(r'IE(\d+)', permalink)
                        fl_match = re.search(r'FL(\d+)', permalink)

                        if ie_match and fl_match:
                            ie_num = ie_match.group(1)
                            fl_num = fl_match.group(1)
                            permalink = f"https://iiif.virginiamemory.com/iiif/2/IE{ie_num}:FL{fl_num}/full/max/0/default.jpg"
                        elif ie_match:
                            ie_num = ie_match.group(1)
                            permalink = f"https://iiif.virginiamemory.com/iiif/2/IE{ie_num}/full/max/0/default.jpg"

                permalink = r2_uploader.upload_url(
                    permalink, in_tqdm=True, raise_on_err=False
                )

            if permalink is None:
                tqdm.write("✗ Unable to download image, skipping")
                continue

        try:
            edtf_date = parse_date(record.get("date"), default_edtf, min_year, max_year)

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
                )
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
                )
        except Exception as e:
            tqdm.write(f"✗ Error creating image: {e}")

        sleep(POLITE_WAIT_SECS)

    # Count records with and without images
    images_imported = sum(1 for record in records if record.get("iiif_full_url"))
    metadata_only = len(records) - images_imported

    print(f"\n✓ Imported {len(records)} records ({images_imported} with images, {metadata_only} metadata only)")

    if save_json:
        json_file = f"collection_{collection_id}_records.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        print(f"Saved all records to {json_file} for analysis")


if __name__ == "__main__":
    main()
