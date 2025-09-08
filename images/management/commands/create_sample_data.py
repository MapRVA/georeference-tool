from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from images.models import Source, Collection, Image
import random


class Command(BaseCommand):
    help = "Create sample data for testing the georeferencing interface"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing data before creating sample data",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing existing data...")
            Image.objects.all().delete()
            Collection.objects.all().delete()
            Source.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Data cleared"))

        # Create sources
        sources_data = [
            {
                "name": "Library of Congress",
                "url": "https://www.loc.gov/pictures/",
                "description": "The Library of Congress Prints and Photographs Division digital collections containing millions of historical images.",
            },
            {
                "name": "Richmond Times-Dispatch Archive",
                "url": "https://www.richmond.com/archive/",
                "description": "Historical newspaper photographs from the Richmond Times-Dispatch covering Virginia history and events.",
            },
            {
                "name": "Virginia Memory",
                "url": "https://www.virginiamemory.com/",
                "description": "Digital collections from the Library of Virginia featuring historical photographs, maps, and documents.",
            },
        ]

        sources = []
        for source_data in sources_data:
            source, created = Source.objects.get_or_create(
                name=source_data["name"], defaults=source_data
            )
            sources.append(source)
            if created:
                self.stdout.write(f"Created source: {source.name}")

        # Create collections
        collections_data = [
            # Library of Congress collections
            {
                "source": sources[0],
                "name": "Historic American Buildings Survey",
                "url": "https://www.loc.gov/pictures/collection/hh/",
                "description": "Architectural photographs documenting historic buildings across America.",
            },
            {
                "source": sources[0],
                "name": "Farm Security Administration",
                "url": "https://www.loc.gov/pictures/collection/fsa/",
                "description": "Depression-era photographs documenting rural America and agricultural life.",
            },
            {
                "source": sources[0],
                "name": "Civil War Glass Negatives",
                "url": "https://www.loc.gov/pictures/collection/cwp/",
                "description": "Civil War era photographs including battlefields, portraits, and camp life.",
            },
            # Richmond Times-Dispatch collections
            {
                "source": sources[1],
                "name": "Richmond Street Scenes",
                "url": "https://www.richmond.com/archive/streets/",
                "description": "Historical street photography of Richmond, Virginia from 1920-1980.",
            },
            {
                "source": sources[1],
                "name": "Virginia Events Coverage",
                "url": "https://www.richmond.com/archive/events/",
                "description": "News photography covering significant events in Virginia history.",
            },
            # Virginia Memory collections
            {
                "source": sources[2],
                "name": "Virginia Towns and Cities",
                "url": "https://www.virginiamemory.com/collections/towns/",
                "description": "Historic photographs of Virginia municipalities and urban development.",
            },
        ]

        collections = []
        for collection_data in collections_data:
            collection, created = Collection.objects.get_or_create(
                source=collection_data["source"],
                name=collection_data["name"],
                defaults=collection_data,
            )
            collections.append(collection)
            if created:
                self.stdout.write(f"Created collection: {collection.name}")

        # Create sample images
        sample_images = [
            # HABS images
            {
                "collection": collections[0],
                "title": "Virginia State Capitol, Richmond",
                "permalink": "https://www.loc.gov/pictures/item/va1234/",
                "description": "West facade of the Virginia State Capitol designed by Thomas Jefferson",
                "year": 1934,
                "month": 6,
                "difficulty": "easy",
            },
            {
                "collection": collections[0],
                "title": "Monticello, Charlottesville",
                "permalink": "https://www.loc.gov/pictures/item/va1235/",
                "description": "Thomas Jefferson's home and architectural masterpiece",
                "year": 1933,
                "month": 8,
                "day": 15,
                "difficulty": "medium",
            },
            {
                "collection": collections[0],
                "title": "Old Dominion University Building",
                "permalink": "https://www.loc.gov/pictures/item/va1236/",
                "description": "Historic academic building at Old Dominion University",
                "year": 1935,
                "difficulty": "hard",
            },
            # FSA images
            {
                "collection": collections[1],
                "title": "Tobacco Farm, Southside Virginia",
                "permalink": "https://www.loc.gov/pictures/item/fsa1237/",
                "description": "Farmers working tobacco fields in rural Virginia",
                "year": 1938,
                "month": 7,
                "difficulty": "medium",
            },
            {
                "collection": collections[1],
                "title": "General Store, Rural Virginia",
                "permalink": "https://www.loc.gov/pictures/item/fsa1238/",
                "description": "Small town general store serving the local community",
                "year": 1936,
                "difficulty": "easy",
            },
            # Civil War images
            {
                "collection": collections[2],
                "title": "Richmond Ruins, 1865",
                "permalink": "https://www.loc.gov/pictures/item/cwp1239/",
                "description": "Aftermath of the evacuation fire in Richmond during the Civil War",
                "year": 1865,
                "month": 4,
                "difficulty": "hard",
            },
            {
                "collection": collections[2],
                "title": "Petersburg Battlefield",
                "permalink": "https://www.loc.gov/pictures/item/cwp1240/",
                "description": "Battlefield scene from the Siege of Petersburg",
                "year": 1864,
                "difficulty": "medium",
            },
            # Richmond Street Scenes
            {
                "collection": collections[3],
                "title": "Broad Street, 1950",
                "permalink": "https://www.richmond.com/archive/broad1950/",
                "description": "Busy commercial district on Broad Street in downtown Richmond",
                "year": 1950,
                "month": 3,
                "difficulty": "easy",
            },
            {
                "collection": collections[3],
                "title": "Monument Avenue",
                "permalink": "https://www.richmond.com/archive/monument1955/",
                "description": "Historic Monument Avenue with Confederate statues",
                "year": 1955,
                "difficulty": "medium",
            },
            # Virginia Events
            {
                "collection": collections[4],
                "title": "State Fair, 1962",
                "permalink": "https://www.richmond.com/archive/statefair1962/",
                "description": "Virginia State Fair midway and attractions",
                "year": 1962,
                "month": 9,
                "difficulty": "hard",
            },
            # Virginia Towns
            {
                "collection": collections[5],
                "title": "Main Street, Lexington",
                "permalink": "https://www.virginiamemory.com/collections/lexington123/",
                "description": "Historic downtown Lexington, Virginia",
                "year": 1925,
                "difficulty": "medium",
            },
            {
                "collection": collections[5],
                "title": "Norfolk Harbor",
                "permalink": "https://www.virginiamemory.com/collections/norfolk456/",
                "description": "Norfolk harbor with ships and maritime activity",
                "year": 1940,
                "month": 11,
                "difficulty": "easy",
            },
            # Additional images without difficulty set
            {
                "collection": collections[0],
                "title": "University of Virginia Rotunda",
                "permalink": "https://www.loc.gov/pictures/item/va2001/",
                "description": "The iconic Rotunda at the University of Virginia",
                "year": 1936,
                "month": 5,
            },
            {
                "collection": collections[1],
                "title": "Farm Family Portrait",
                "permalink": "https://www.loc.gov/pictures/item/fsa2002/",
                "description": "Rural Virginia family on their farm during the Depression",
                "year": 1937,
            },
            {
                "collection": collections[3],
                "title": "Capitol Square",
                "permalink": "https://www.richmond.com/archive/capitol1960/",
                "description": "Aerial view of Virginia's Capitol Square",
                "year": 1960,
                "month": 4,
                "day": 10,
            },
        ]

        created_count = 0
        for image_data in sample_images:
            image, created = Image.objects.get_or_create(
                permalink=image_data["permalink"], defaults=image_data
            )
            if created:
                created_count += 1
                self.stdout.write(
                    f"Created image: {image.title or f'Image #{image.id}'}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSample data creation complete!\n"
                f"Created {len(sources)} sources, {len(collections)} collections, and {created_count} images.\n"
                f"You can now browse at: http://localhost:8000/browse/"
            )
        )

        # Show some usage examples
        self.stdout.write("\nNext steps:")
        self.stdout.write("1. Visit http://localhost:8000/browse/ to see all sources")
        self.stdout.write(
            "2. Visit http://localhost:8000/georeference/ to start georeferencing"
        )
        self.stdout.write(
            "3. Use admin interface at http://localhost:8000/admin/ (admin/admin)"
        )
        self.stdout.write("4. Try georeferencing some images to test the workflow")
