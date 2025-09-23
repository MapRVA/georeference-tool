import requests
import re
import json
import os

# Load or fetch data
if os.path.exists("insurance_maps.json"):
    with open("insurance_maps.json", "r") as f:
        data = json.load(f)
else:
    response = requests.get("https://oldinsurancemaps.net/viewer/richmond-va/")
    html = response.text
    match = re.search(
        r'<script id="viewer-props" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    data = json.loads(match.group(1))
    with open("insurance_maps.json", "w") as f:
        json.dump(data, f)

# Extract data and save to new JSON
layers = []
for map_item in data["MAPS"]:
    if "item_lookup" in map_item and "prepared" in map_item["item_lookup"]:
        for prepared_item in map_item["item_lookup"]["prepared"]:
            if "slug" in prepared_item:
                prepared_slugs.add(prepared_item["slug"])

print(f"Found {len(prepared_slugs)} prepared entries")


def extract_cogs_recursive(obj):
    """Recursively extract COG URLs, but only for prepared entries"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "cog" and isinstance(value, str) and value.strip():
                # Extract base slug from COG URL to match against prepared entries
                filename = os.path.basename(value)
                # Remove the __XXXXX_XX.tif part to get the base slug
                slug_match = re.match(r"(.+?)__[^_]+_\d+\.tif$", filename)
                if slug_match:
                    base_slug = slug_match.group(1)

                    # Check for exact match first
                    if base_slug in prepared_slugs:
                        cog_urls.append(value)
                        print(f"Including COG {base_slug} (exact match)")
                        continue

                    # Check for page-based match (e.g., p804_1 COG matches p804_2, p804_3, etc. prepared entries)
                    # Extract page pattern: richmond_va_YYYY_vol_X_pNNN
                    page_pattern_match = re.match(r"^(.+_p\d+)_\d+$", base_slug)
                    if page_pattern_match:
                        page_pattern = page_pattern_match.group(1)
                        # Check if any prepared slug starts with this page pattern
                        for prepared_slug in prepared_slugs:
                            if prepared_slug.startswith(page_pattern + "_"):
                                cog_urls.append(value)
                                print(
                                    f"Including COG {base_slug} for page with prepared regions starting with {page_pattern}"
                                )
                                break
            else:
                extract_cogs_recursive(value)
    elif isinstance(obj, list):
        for item in obj:
            extract_cogs_recursive(item)


# Extract COGs from the full data
extract_cogs_recursive(data)

# Remove duplicates while preserving order
seen = set()
unique_cog_urls = []
for url in cog_urls:
    if url not in seen:
        seen.add(url)
        unique_cog_urls.append(url)

print(f"Found {len(unique_cog_urls)} unique COG URLs")

# Also save to file
with open("cog_urls.txt", "w") as f:
    for url in unique_cog_urls:
        f.write(url + "\n")

print(f"COG URLs saved to cog_urls.txt")


# Download COG files organized by year
def extract_year_from_url(url):
    """Extract year from URL like richmond_va_1952_vol_5_p501"""
    match = re.search(r"richmond_va_(\d{4})", url)
    return match.group(1) if match else "unknown"


def download_cog(url, filepath):
    """Download a COG file if it doesn't exist"""
    if os.path.exists(filepath):
        print(f"Skipping existing file: {filepath}")
        return True

    try:
        print(f"Downloading: {os.path.basename(filepath)}")
        response = requests.get(url, stream=True)
        response.raise_for_status()

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Downloaded: {filepath}")
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False


# Group URLs by year and download
print(f"\nStarting download of {len(unique_cog_urls)} COG files...")
year_counts = {}
downloaded_count = 0
skipped_count = 0
failed_count = 0

for url in unique_cog_urls:
    year = extract_year_from_url(url)
    filename = os.path.basename(url)
    filepath = os.path.join(f"richmond_va_{year}", filename)

    # Track year counts
    year_counts[year] = year_counts.get(year, 0) + 1

    if os.path.exists(filepath):
        skipped_count += 1
        if skipped_count % 50 == 0:  # Print progress for skipped files
            print(f"Skipped {skipped_count} existing files...")
    else:
        success = download_cog(url, filepath)
        if success:
            downloaded_count += 1
        else:
            failed_count += 1

print(f"\nDownload summary:")
print(f"Files by year: {dict(sorted(year_counts.items()))}")
print(f"Downloaded: {downloaded_count}")
print(f"Skipped (already existed): {skipped_count}")
print(f"Failed: {failed_count}")
print(f"Total processed: {len(unique_cog_urls)}")
