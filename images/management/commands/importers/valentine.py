"""
Valentine Museum importer.

Scrapes archival records from The Valentine Museum's Rediscovery Software API.
"""

import re
import sys
from time import sleep

import requests
from tqdm import tqdm

from images.models import Collection, Image, PreCollection, PreImage, Source
from images.utils import R2Uploader

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


def create_collection_if_not_exist(
    source, readable_primary_key, use_precollection=False
):
    """Get or create a collection using the GetRecordDetails API for group data"""
    url = "https://valentine.rediscoverysoftware.com/ProficioWcfServices/ProficioWcfService.svc/GetRecordDetails"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "MapRVA Yesterdays (https://github.com/MapRVA/yesterdays)",
    }
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

    collection_url = f"https://valentine.rediscoverysoftware.com/MADetailG.aspx?rID={readable_primary_key}&db=group&dir=VALARCH"

    # Show collection details to user for confirmation
    print(f"\n  {collection_type.title()} Details for '{readable_primary_key}':")
    print(f"  Name: {collection_name}")
    print(f"  Source: {source.name}")
    print(f"  URL: {collection_url}")
    print(f"  Description: {description}")
    if use_precollection:
        print("  Type: Pre-collection (for review)")

    if input(f"\n  Create this {collection_type}? [y/N] ").strip().lower() == "y":
        if use_precollection:
            collection = PreCollection.objects.create(
                source=source,
                name=collection_name,
                url=collection_url,
                description=description,
            )
        else:
            collection = Collection.objects.create(
                source=source,
                name=collection_name,
                url=collection_url,
                description=description,
            )
        print(f"Created {collection_type}: {collection.name}")
        return collection
    else:
        return None


def get_archival_children(archival_number: str, table: str):
    url = "https://valentine.rediscoverysoftware.com/ProficioWcfServices/ProficioWcfService.svc/GetArchivalChildren"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "MapRVA Yesterdays (https://github.com/MapRVA/yesterdays)",
    }
    data = {
        "TableName": table,
        "ArchivalNumber": archival_number,
        "Directory": "VALARCH",
    }

    response = requests.post(url, headers=headers, json=data)
    json_response = response.json()
    xml_content = json_response.get("d", "")

    # Report high-level info of children found
    member_data = {
        # Official Valentine reference number
        "archival_number": re.findall(
            r"<ArchivalNumber>(.*?)</ArchivalNumber>", xml_content
        ),
        # Archival level (GROUP/SERIES-FILEUNIT#BIBLIO
        "table_name": re.findall(r"<TableName>(.*?)</TableName>", xml_content),
    }
    return member_data


def get_record_details(
    readable_primary_key: str,
    last_possible_year=None,
    first_possible_year=None,
    date_overrides=None,
):
    url = "https://valentine.rediscoverysoftware.com/ProficioWcfServices/ProficioWcfService.svc/GetRecordDetails"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "MapRVA Yesterdays (https://github.com/MapRVA/yesterdays)",
    }
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
    inscription_match = re.search(r"<categ_3>(.*?)</categ_3>", xml_content)

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

    if inscription_match and "description" in result:
        result["description"] += "\n\nInscription: " + inscription_match.group(1)

    if geo_match and "description" in result:
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

    season_map = {
        "spring": 21,
        "summer": 22,
        "autumn": 23,
        "fall": 23,
        "winter": 24,
    }

    # Process date further to extract year and month
    if date_match:
        date_str = date_match.group(1).strip()
        result["original_date"] = date_str

        # Check for user-provided date overrides first
        if date_overrides and date_str in date_overrides:
            result["edtf_date"] = date_overrides[date_str]
            return result

        if first_possible_year:
            # Match "Pre YYYY-YYYY"
            pre_year_range_match = re.match(r"^Pre\s+\d{4}-(\d{4})$", date_str)
            if pre_year_range_match:
                end_year = pre_year_range_match.group(1)
                result["edtf_date"] = f"[{first_possible_year}..{end_year}]"
                return result

            # Match "Pre YYYY"
            pre_year_match = re.match(r"^Pre\s+(\d{4})$", date_str)
            if pre_year_match:
                end_year = pre_year_match.group(1)
                result["edtf_date"] = f"[{first_possible_year}..{end_year}]"
                return result

        if last_possible_year:
            post_year_range_match = re.match(r"^Post\s+(\d{4})-\d{4}$", date_str)
            if post_year_range_match:
                first_year = post_year_range_match.group(1)
                result["edtf_date"] = f"[{first_year}..{last_possible_year}]"
                return result

            # Match "Post YYYY"
            post_year_match = re.match(r"^Post\s+(\d{4})$", date_str)
            if post_year_match:
                first_year = post_year_match.group(1)
                result["edtf_date"] = f"[{first_year}..{last_possible_year}]"
                return result

        post_pre_year_match = re.match(r"^Post\s+(\d{4})\s*-\s*Pre\s+(\d{4})", date_str)
        if post_pre_year_match:
            first_year = post_pre_year_match.group(1)
            last_year = post_pre_year_match.group(2)
            result["edtf_date"] = f"[{first_year}..{last_year}]"
            return result

        year_match = re.match(r"^(\d{4})$", date_str)
        if year_match:
            result["edtf_date"] = year_match.group(1)
            return result

        early_year_match = re.match(r"^E|early\s+(\d{4})$", date_str)
        if early_year_match:
            year = early_year_match.group(1)
            result["edtf_date"] = f"{year}-37"
            return result

        # Try "Circa YYYY" format
        circa_match = re.match(r"(?i)(?:c|Circa|c\.)\s+(\d{4})$", date_str)
        if circa_match:
            result["edtf_date"] = circa_match.group(1) + "~"
            return result

        # Try YYYY-YYYY year range
        # Optionally allow Circa prefix...not much we can do about that.
        year_range_match = re.match(
            r"^(?:(?:c|Circa|c\.)\s+)?(\d{4})\s*-\s*(?:(?:c|Circa|c\.)\s+)?(\d{4})$",
            date_str,
        )
        if year_range_match:
            first_year = int(year_range_match.group(1))
            second_year = int(year_range_match.group(2))
            if second_year == (first_year + 1):
                result["edtf_date"] = f"[{first_year},{second_year}]"
            else:
                result["edtf_date"] = f"[{first_year}..{second_year}]"
            return result

        # Try "MM/YYYY-MM/YYYY" month-year range format (e.g., "12/1976-1/1977")
        month_year_range_match = re.match(
            r"^(\d{1,2})/(\d{4})\s*-\s*(\d{1,2})/(\d{4})$", date_str
        )
        if month_year_range_match:
            first_month = month_year_range_match.group(1).zfill(2)
            first_year = month_year_range_match.group(2)
            second_month = month_year_range_match.group(3).zfill(2)
            second_year = month_year_range_match.group(4)
            result["edtf_date"] = (
                f"[{first_year}-{first_month}..{second_year}-{second_month}]"
            )
            return result

        # Try "MM/YYYY" format
        month_year_match = re.match(r"^(\d{1,2})/(\d{4})$", date_str)
        if month_year_match:
            result["edtf_date"] = (
                month_year_match.group(2) + "-" + month_year_match.group(1).zfill(2)
            )
            return result

        month_day_year_match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_str)
        if month_day_year_match:
            # BE CAREFUL! Take note of different order in EDTF
            result["edtf_date"] = (
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
                result["edtf_date"] = (
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
                result["edtf_date"] = (
                    month_name_day_year_match.group(3)
                    + "-"
                    + str(month_map[month_name]).zfill(2)
                    + "-"
                    + month_name_day_year_match.group(2).zfill(2)
                )
                return result

        # Try Season YYYY
        season_year_match = re.match(r"^(\w+)\s+(\d{4})$", date_str)
        if season_year_match:
            season_name = season_year_match.group(1).lower()
            if season_name in season_map:
                result["edtf_date"] = (
                    season_year_match.group(2) + "-" + str(season_map[season_name])
                )
                return result

        # If no matches found, breakpoint for debugging
        print("No date found!")
        breakpoint()

    return result


def add_arguments(parser):
    """Add valentine-specific arguments to the parser."""
    parser.add_argument("archive_id", type=str)
    parser.add_argument("search_table", nargs="?", default="GROUP")
    parser.add_argument(
        "--hotlink",
        action="store_true",
        help="Hotlink images instead of uploading to R2",
    )
    parser.add_argument(
        "--last-possible-year",
        type=int,
        help='Last possible year for date ranges like "Post YYYY-YYYY"',
    )
    parser.add_argument(
        "--first-possible-year",
        type=int,
        help='First possible year for date ranges like "Pre YYYY" or "Pre YYYY-YYYY"',
    )
    parser.add_argument(
        "--date-override",
        action="append",
        default=[],
        help='Override a specific date string with an EDTF value (e.g., "Late 20th Century=[1975..1980]"). Can be specified multiple times.',
    )


def handle(options):
    """Run the Valentine Museum import."""
    archive_id = options["archive_id"]
    search_table = options["search_table"]
    hotlink = options["hotlink"]
    last_possible_year = options["last_possible_year"]
    first_possible_year = options["first_possible_year"]

    # Parse date overrides into a dict
    date_overrides = {}
    for override in options["date_override"]:
        if "=" not in override:
            print(f"✗ Invalid date override (missing '='): {override}")
            print('  Expected format: "Date String=EDTF value"')
            sys.exit(1)
        date_str, edtf_value = override.split("=", 1)
        date_overrides[date_str] = edtf_value

    if date_overrides:
        print(f"Date overrides: {len(date_overrides)}")
        for date_str, edtf_value in date_overrides.items():
            print(f'  "{date_str}" → {edtf_value}')

    source = create_source_if_not_exist()
    collection = create_collection_if_not_exist(
        source, archive_id, use_precollection=hotlink
    )

    if not collection:
        return

    archival_children = get_archival_children(archive_id, table=search_table)

    items_resolved = {"archival_number": [], "table_name": []}
    items_unresolved = {"archival_number": [], "table_name": []}

    for i, table in enumerate(archival_children["table_name"]):
        if table == "BIBLIO":
            items_resolved["archival_number"].append(
                archival_children["archival_number"][i]
            )
            items_resolved["table_name"].append(table)
        if table != "BIBLIO":
            items_unresolved["archival_number"].append(
                archival_children["archival_number"][i]
            )
            items_unresolved["table_name"].append(table)

    # Recurse down the archival hierarchy until we have all BIBLIO items
    while len(items_unresolved["table_name"]) != 0:
        hold = {"archival_number": [], "table_name": []}

        for i in range(len(items_unresolved["archival_number"])):
            archival_children = get_archival_children(
                items_unresolved["archival_number"][i],
                items_unresolved["table_name"][i],
            )
            for i, table in enumerate(archival_children["table_name"]):
                if table == "BIBLIO":
                    items_resolved["archival_number"].append(
                        archival_children["archival_number"][i]
                    )
                    items_resolved["table_name"].append(table)
                if table != "BIBLIO":
                    hold["archival_number"].append(
                        archival_children["archival_number"][i]
                    )
                    hold["table_name"].append(table)

        items_unresolved = hold
        sleep(POLITE_WAIT_SECS)

    r2_uploader = None if hotlink else R2Uploader()

    skip_count = 0
    for child in tqdm(items_resolved["archival_number"]):
        # Check for existing images in the appropriate model
        if hotlink:
            existing_by_ref = PreImage.objects.filter(ref=child).exists()
        else:
            existing_by_ref = Image.objects.filter(ref=child).exists()
        if existing_by_ref:
            skip_count += 1
            continue
        elif skip_count > 0:
            tqdm.write(f"Skipped {skip_count} images that already exist")
            skip_count = 0

        sleep(POLITE_WAIT_SECS)
        record = get_record_details(
            child,
            last_possible_year=last_possible_year,
            first_possible_year=first_possible_year,
            date_overrides=date_overrides,
        )

        # Do we have an image URL to try and download?
        if "permalink" not in record:
            tqdm.write("      ✗ No image URL found for record, skipping")
            continue

        # Try downloading the image (and uploading it to R2)
        if not hotlink:
            record["permalink"] = r2_uploader.upload_url(
                record["permalink"],
                in_tqdm=True,
                raise_on_err=False,
            )

        # Were we successful in downloading the image?
        if record["permalink"] is None:
            tqdm.write("      ✗ Unable to download image, skipping")
            continue

        try:
            tqdm.write("      → Inserting image {}".format(record["original_url"]))

            # Create the appropriate image type based on hotlink option
            if hotlink:
                image = PreImage.objects.create(
                    collection=collection,
                    title=record["title"],
                    permalink=record["permalink"],
                    ref=record["ref"],
                    description=record.get("description", ""),
                    creator=record.get("creator", ""),
                    original_date=record.get("original_date"),
                    edtf_date=record.get("edtf_date"),
                    license=options.get("license"),
                )
                tqdm.write(f"      → Created pre-image ID: {image.id}")
            else:
                image = Image.objects.create(
                    collection=collection,
                    title=record["title"],
                    permalink=record["permalink"],
                    ref=record["ref"],
                    original_url=record["original_url"],
                    description=record.get("description", ""),
                    creator=record.get("creator", ""),
                    original_date=record.get("original_date"),
                    edtf_date=record.get("edtf_date"),
                    license=options.get("license"),
                )
                tqdm.write(f"      → Created image ID: {image.id}")
        except Exception as e:
            tqdm.write(f"      ✗ Error creating image: {e}")
