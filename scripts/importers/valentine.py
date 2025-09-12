#!/usr/bin/env python3
"""
Valentine Museum Mary Wingfield Scott Photograph Collection Scraper

Scrapes the Mary Wingfield Scott Photograph Collection from The Valentine Museum's
digital archives, extracting image data and high-resolution image URLs.

Usage:
    python mary_wingfield_scott.py --dry-run
    python mary_wingfield_scott.py --max-images 10 --dry-run
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

POLITE_WAIT_SECS = 0.75


def create_source_if_not_exist():
    """Get or create The Valentine museum source"""
    source, created = Source.objects.get_or_create(
        name="The Valentine",
        defaults={
            "url": "https://thevalentine.org/",
            "description": "The Valentine is a museum in Richmond, Virginia dedicated to collecting, preserving and interpreting Richmond's history. Founded in 1898, it houses extensive collections documenting the social and cultural history of Richmond and the surrounding region.",
            "public": True,
        },
    )
    if created:
        print(f"Created source: {source.name}")
    else:
        print(f"Using existing source: {source.name}")
    return source


def create_collection_if_not_exist(source, readable_primary_key):
    """Get or create a collection using the GetRecordDetails API for group data"""
    url = "https://valentine.rediscoverysoftware.com/ProficioWcfServices/ProficioWcfService.svc/GetRecordDetails"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = {
        "TableName": "group",
        "Directory": "VALARCH",
        "FieldList": "record_id,group_nbr,group_nam,author,inc_dte,abstract,bulk_dte,volume,history,scope,language,arrangemnt,user_1,categ_12,sub_pers,sub_corp,sub_form,sub_geo,imagekey",
        "IncludeImage": True,
        "RecordID": -1,
        "readablePrimaryKey": readable_primary_key,
    }

    response = requests.post(url, headers=headers, json=data)
    json_response = response.json()
    xml_content = json_response.get("d", "")

    # Extract collection name and other details
    collection_name_match = re.search(r"<group_nam>(.*?)</group_nam>", xml_content)
    abstract_match = re.search(r"<abstract>(.*?)</abstract>", xml_content)

    collection_name = (
        collection_name_match.group(1)
        if collection_name_match
        else readable_primary_key
    )
    description = (
        abstract_match.group(1)
        if abstract_match
        else f"Collection from The Valentine museum archives: {readable_primary_key}"
    )

    # Extract additional collection details for display
    author_match = re.search(r"<author>(.*?)</author>", xml_content)
    inc_dte_match = re.search(r"<inc_dte>(.*?)</inc_dte>", xml_content)
    bulk_dte_match = re.search(r"<bulk_dte>(.*?)</bulk_dte>", xml_content)

    # Check if collection already exists
    existing_collection = Collection.objects.filter(
        source=source, name=collection_name
    ).first()
    if existing_collection:
        print(f"  ✓ Using existing collection: {existing_collection.name}")
        return existing_collection

    collection_url = f"https://valentine.rediscoverysoftware.com/MADetailG.aspx?rID={readable_primary_key}&db=group&dir=VALARCH"

    # Show collection details to user for confirmation
    print(f"\n  Collection Details for '{readable_primary_key}':")
    print(f"  Name: {collection_name}")
    print(f"  Source: {source.name}")
    print(f"  URL: {collection_url}")
    print(f"  Description: {description}")

    if click.confirm("\n  Create this collection?"):
        collection = Collection.objects.create(
            source=source,
            name=collection_name,
            url=collection_url,
            description=description,
        )
        print(f"Created collection: {collection.name}")
        return collection
    else:
        return None


def get_archival_children(archival_number: str):
    url = "https://valentine.rediscoverysoftware.com/ProficioWcfServices/ProficioWcfService.svc/GetArchivalChildren"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = {
        "TableName": "GROUP",
        "ArchivalNumber": archival_number,
        "Directory": "VALARCH",
    }

    response = requests.post(url, headers=headers, json=data)
    json_response = response.json()
    xml_content = json_response.get("d", "")
    archival_numbers = re.findall(
        r"<ArchivalNumber>(.*?)</ArchivalNumber>", xml_content
    )
    return archival_numbers


def get_record_details(readable_primary_key: str):
    url = "https://valentine.rediscoverysoftware.com/ProficioWcfServices/ProficioWcfService.svc/GetRecordDetails"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = {
        "TableName": "biblio",
        "Directory": "VALARCH",
        "FieldList": "record_id,biblio_nbr,group_nbr,series_nbr,fileunit_nbr,edition,title,author,sortable14,origin,categ_12,categ_16,categ_1,categ_9[2],categ_3,user_2,user_4,sub_pers,sub_corp,sub_topic,sub_geo,categ_6,categ_7,categ_8,categ_13,subjects,categ_20,file_name",
        "IncludeImage": True,
        "RecordID": -1,
        "readablePrimaryKey": readable_primary_key,
    }

    response = requests.post(url, headers=headers, json=data)
    json_response = response.json()
    xml_content = json_response.get("d", "")

    # Extract fields using regex
    title_match = re.search(r"<title>(.*?)</title>", xml_content)
    description_match = re.search(r"<categ_16>(.*?)</categ_16>", xml_content)
    date_match = re.search(r"<origin>(.*?)</origin>", xml_content)
    creator_match = re.search(r"<author>(.*?)</author>", xml_content)
    geo_match = re.search(r"<sub_geo>(.*?)</sub_geo>", xml_content)
    image_match = re.search(r"<FullImage>(.*?)</FullImage>", xml_content)

    # Create dictionary for extracted data
    result = {
        "original_url": f"https://valentine.rediscoverysoftware.com/MADetailB.aspx?rID={readable_primary_key}&db=biblio&dir=VALARCH",
        "ref": readable_primary_key,
    }

    if title_match:
        result["title"] = title_match.group(1)
    else:
        print("No title found!")
        breakpoint()

    if description_match:
        result["description"] = description_match.group(1)

    if creator_match:
        result["creator"] = creator_match.group(1)

    if geo_match:
        result["description"] += "\n\nGeographic Description: " + geo_match.group(1)

    # Process image URL to create proper downloadable URL
    if image_match:
        # Replace backslashes with URL-encoded backslashes
        url_encoded_path = image_match.group(1).replace("\\", "%5C")
        result["permalink"] = (
            f"https://valentine.rediscoverysoftware.com/FullImages/{url_encoded_path}"
        )
    else:
        print("No image found!")

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

    # Process date further to extract year and month
    if date_match:
        date_str = date_match.group(1).strip()

        year_match = re.match(r"^(\d{4})$", date_str)
        if year_match:
            result["etdf_date"] = year_match.group(1)
            return result

        # Try "Circa YYYY" format
        circa_match = re.match(r"(?i)(?:circa|c\.)\s+(\d{4})$", date_str)
        if circa_match:
            result["etdf_date"] = circa_match.group(1) + "~"
            return result

        # Try YYYY-YYYY year range
        year_range_match = re.match(r"^(\d{4})-(\d{4})$", date_str)
        if year_range_match:
            result["etdf_date"] = (
                year_range_match.group(1) + "/" + year_range_match.group(2)
            )
            return result

        # Try "MM/YYYY" format
        month_year_match = re.match(r"^(\d{1,2})/(\d{4})$", date_str)
        if month_year_match:
            result["etdf_date"] = (
                month_year_match.group(2) + "-" + month_year_match.group(1).zfill(2)
            )
            return result

        month_day_year_match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_str)
        if month_day_year_match:
            # BE CAREFUL! Take note of different order in EDTF
            result["etdf_date"] = (
                month_day_year_match.group(3)
                + "-"
                + month_day_year_match.group(1).zfill(2)
                + "-"
                + month_day_year_match.group(2).zfill(2)
            )
            return result

        # Try "Month YYYY" format (e.g., "June 1993")
        month_name_year_match = re.match(r"^(\w+)\s+(\d{4})$", date_str)
        if month_name_year_match:
            month_name = month_name_year_match.group(1).lower()
            if month_name in month_map:
                result["etdf_date"] = (
                    month_name_year_match.group(2)
                    + "-"
                    + str(month_map[month_name]).zfill(2)
                )
                return result

        # Try "Month Day, YYYY" format (e.g., "June 13, 1993")
        month_name_day_year_match = re.match(
            r"^(\w+)\s+(\d{1,2})(?:,)?\s+(\d{4})$", date_str
        )
        if month_name_day_year_match:
            month_name = month_name_day_year_match.group(1).lower()
            if month_name in month_map:
                # BE CAREFUL! Take note of different order in EDTF
                result["etdf_date"] = (
                    month_name_day_year_match.group(3)
                    + "-"
                    + str(month_map[month_name]).zfill(2)
                    + "-"
                    + month_name_day_year_match.group(2).zfill(2)
                )
                return result

        # If no matches found, breakpoint for debugging
        print("No date found!")
        breakpoint()

    return result


@click.command()
@click.argument("archive_id", default="PHC0039")
def main(archive_id):
    """Scrape archival records from The Valentine Museum's digital archives."""

    source = create_source_if_not_exist()
    collection = create_collection_if_not_exist(source, archive_id)

    if collection:
        archival_children = get_archival_children(archive_id)

        r2_uploader = R2Uploader()

        for child in tqdm(archival_children):
            existing_by_ref = Image.objects.filter(ref=child).exists()
            if existing_by_ref:
                tqdm.write("      → Already exists, skipping")
                continue

            sleep(POLITE_WAIT_SECS)
            record = get_record_details(child)

            if "permalink" not in record:
                tqdm.write("      ✗ No image URL found for record, skipping")
                continue

            record["permalink"] = r2_uploader.upload_url(
                record["permalink"],
                in_tqdm=True
            )

            try:
                tqdm.write("      → Inserting image {}".format(record["original_url"]))
                image = Image.objects.create(
                    collection=collection,
                    title=record["title"],
                    permalink=record["permalink"],
                    ref=record["ref"],
                    original_url=record["original_url"],
                    description=record.get("description", ""),
                    creator=record.get("creator", ""),
                    original_date=record.get("original_date"),
                    edtf_date=record.get("etdf_date"),
                )
                tqdm.write(f"      → Created image ID: {image.id}")
            except Exception as e:
                tqdm.write(f"      ✗ Error creating image: {e}")
                breakpoint()


if __name__ == "__main__":
    main()
