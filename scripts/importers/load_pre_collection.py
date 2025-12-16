#!/usr/bin/env python3
"""
Pre Collection importer

This script allows the user to select a Pre Collection, and import any reviewed images into a Collection.

Usage:
    uv run scripts/importers/load_pre_collection.py
"""

import os
import sys

import click
from tqdm import tqdm

# Add the Django project to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(script_dir, "..", "..")
sys.path.insert(0, project_root)

# Change to project directory for Django
os.chdir(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "yesterdays.settings")

import django

django.setup()

from images.models import Collection, Image, PreCollection

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


def list_pre_collections():
    """List all available PreCollections with their details"""
    pre_collections = PreCollection.objects.all().order_by("source__name", "name")

    if not pre_collections.exists():
        click.echo("No PreCollections found.")
        return []

    click.echo("\nAvailable PreCollections:")
    click.echo("=" * 60)

    collection_data = []
    for i, pre_collection in enumerate(pre_collections, 1):
        reviewed_count = pre_collection.images.filter(keep=True).count()
        not_imported_count = pre_collection.images.filter(
            keep=True, imported=False
        ).count()
        total_count = pre_collection.images.count()

        click.echo(f"{i:2d}. {pre_collection.source.name} - {pre_collection.name}")
        click.echo(f"    Total images: {total_count}")
        click.echo(f"    Reviewed (keep=True): {reviewed_count}")
        click.echo(f"    Not yet imported: {not_imported_count}")
        click.echo(f"    Complete: {'Yes' if pre_collection.complete else 'No'}")
        click.echo()

        collection_data.append(
            {
                "index": i,
                "pre_collection": pre_collection,
                "reviewed_count": reviewed_count,
                "not_imported_count": not_imported_count,
                "total_count": total_count,
            }
        )

    return collection_data


def select_pre_collection():
    """Allow user to select a PreCollection interactively"""
    collection_data = list_pre_collections()

    if not collection_data:
        return None

    while True:
        try:
            choice = click.prompt(
                f"Select a PreCollection (1-{len(collection_data)}) or 0 to exit",
                type=int,
            )

            if choice == 0:
                return None
            elif 1 <= choice <= len(collection_data):
                selected = collection_data[choice - 1]
                pre_collection = selected["pre_collection"]

                click.echo(
                    f"\nSelected: {pre_collection.source.name} - {pre_collection.name}"
                )
                click.echo(f"Description: {pre_collection.description}")
                click.echo(f"URL: {pre_collection.url}")
                click.echo(f"Images to import: {selected['not_imported_count']}")

                if click.confirm("\nConfirm this selection?"):
                    return pre_collection
            else:
                click.echo(
                    f"Please enter a number between 1 and {len(collection_data)}"
                )

        except (ValueError, click.Abort):
            click.echo("Invalid input. Please enter a number.")


def create_collection_from_pre_collection(pre_collection):
    """Create or get a Collection based on the PreCollection"""
    # Check if a collection with the same name already exists
    existing_collection = Collection.objects.filter(
        source=pre_collection.source, name=pre_collection.name
    ).first()

    if existing_collection:
        click.echo(f"Using existing Collection: {existing_collection.name}")
        return existing_collection

    # Show collection details for confirmation
    click.echo("\nCreating new Collection:")
    click.echo(f"  Source: {pre_collection.source.name}")
    click.echo(f"  Name: {pre_collection.name}")
    click.echo(f"  URL: {pre_collection.url}")
    click.echo(f"  Description: {pre_collection.description}")

    if click.confirm("\nCreate this Collection?"):
        collection = Collection.objects.create(
            source=pre_collection.source,
            name=pre_collection.name,
            url=pre_collection.url,
            description=pre_collection.description,
            public=True,  # Default to public, can be changed later
        )
        click.echo(f"✓ Created Collection: {collection.name}")
        return collection
    else:
        return None


def import_pre_images_to_collection(pre_collection, collection, upload_to_r2=True):
    """Import reviewed PreImages into the Collection"""
    # Get all reviewed images that haven't been imported yet
    pre_images_to_import = pre_collection.images.filter(keep=True, imported=False)

    if not pre_images_to_import.exists():
        click.echo("No reviewed images found to import.")
        return 0

    click.echo(f"Found {pre_images_to_import.count()} reviewed images to import.")

    if upload_to_r2:
        try:
            r2_uploader = R2Uploader()
            click.echo("✓ R2 uploader initialized successfully.")
        except R2UploaderError as e:
            click.echo(f"✗ R2 uploader initialization failed: {e}")
            click.echo("Images will be imported with original permalinks (hotlinked).")
            upload_to_r2 = False

    imported_count = 0
    skipped_count = 0

    with tqdm(pre_images_to_import, desc="Importing images") as pbar:
        for pre_image in pbar:
            try:
                # Check if image already exists in the collection (by ref if available, otherwise by title)
                existing_image = None
                if pre_image.ref:
                    existing_image = Image.objects.filter(
                        collection=collection, ref=pre_image.ref
                    ).first()
                else:
                    existing_image = Image.objects.filter(
                        collection=collection, title=pre_image.title
                    ).first()

                if existing_image:
                    tqdm.write(f"      → Image already exists: {pre_image.title}")
                    skipped_count += 1
                    # Mark as imported even if it already exists
                    pre_image.imported = True
                    pre_image.save(update_fields=["imported"])
                    continue

                # Prepare image data
                permalink = pre_image.permalink

                # Upload to R2 if enabled
                if upload_to_r2:
                    try:
                        permalink = r2_uploader.upload_url(
                            pre_image.permalink, in_tqdm=True, raise_on_err=False
                        )
                        if permalink is None:
                            tqdm.write(
                                f"      ✗ Failed to upload {pre_image.title}, using original URL"
                            )
                            permalink = pre_image.permalink
                    except Exception as e:
                        tqdm.write(
                            f"      ✗ R2 upload error for {pre_image.title}: {e}"
                        )
                        permalink = pre_image.permalink

                # Create the Image in the Collection
                image = Image.objects.create(
                    collection=collection,
                    title=pre_image.title,
                    permalink=permalink,
                    description=pre_image.description or "",
                    license_title=pre_image.license_title,
                    license_permalink=pre_image.license_permalink,
                    creator=pre_image.creator,
                    ref=pre_image.ref,
                    original_date=pre_image.original_date,
                    edtf_date=pre_image.edtf_date,
                    # Set original_url to the pre_image permalink for reference
                    original_url=pre_image.permalink,
                )

                # Mark the PreImage as imported
                pre_image.imported = True
                pre_image.save(update_fields=["imported"])

                imported_count += 1
                tqdm.write(f"      → Imported: {image.title} (ID: {image.id})")

            except Exception as e:
                tqdm.write(f"      ✗ Error importing {pre_image.title}: {e}")
                continue

    click.echo("\n✓ Import complete!")
    click.echo(f"  Imported: {imported_count} images")
    click.echo(f"  Skipped (already exist): {skipped_count} images")

    return imported_count


@click.command()
@click.option(
    "--hotlink",
    is_flag=True,
    help="Hotlink images instead of uploading to R2",
)
def main(hotlink=False):
    """Import reviewed images from a PreCollection into a Collection."""

    click.echo("PreCollection Import Tool")
    click.echo("=" * 40)

    # Step 1: Select PreCollection
    pre_collection = select_pre_collection()
    if not pre_collection:
        click.echo("No PreCollection selected. Exiting.")
        return

    # Step 2: Check if there are reviewed images to import
    reviewed_images = pre_collection.images.filter(keep=True, imported=False)
    if not reviewed_images.exists():
        click.echo(f"No unimported reviewed images found in '{pre_collection.name}'.")
        return

    # Step 3: Create or get Collection
    collection = create_collection_from_pre_collection(pre_collection)
    if not collection:
        click.echo("Collection creation cancelled. Exiting.")
        return

    # Step 4: Import the images
    upload_to_r2 = not hotlink
    imported_count = import_pre_images_to_collection(
        pre_collection, collection, upload_to_r2=upload_to_r2
    )

    if imported_count > 0:
        click.echo(
            f"\n✓ Successfully imported {imported_count} images from PreCollection to Collection!"
        )
        click.echo(
            f"  PreCollection: {pre_collection.source.name} - {pre_collection.name}"
        )
        click.echo(f"  Collection: {collection.source.name} - {collection.name}")
    else:
        click.echo("\nNo images were imported.")


if __name__ == "__main__":
    main()
