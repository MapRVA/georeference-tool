import re
from time import sleep
import requests
from tqdm import tqdm

from django.core.management.base import BaseCommand
from images.models import Collection, Image, Source
from images.tasks import generate_iiif_tiles
from images.utils import R2Uploader

POLITE_WAIT_SECS = 2.0  # Wikimedia is generally faster than LoC but still requires respect


class Command(BaseCommand):
    help = "Interactively import images from Wikimedia Commons into the Yesterdays database."

    def add_arguments(self, parser):
        parser.add_argument("--max-items", type=int, default=None, help="Max items to process")
        parser.add_argument("--query", type=str, help="Initial search query hint")

    def handle(self, *args, **options):
        source = self.get_or_create_wikimedia_source()
        collection_info = self.get_collection_info(options.get('query'))
        collection = self.create_collection_if_not_exist(source, collection_info)

        if not collection:
            self.stdout.write("Collection creation cancelled.")
            return

        r2_uploader = R2Uploader()
        self.handle_import(collection, collection_info, options['max_items'], r2_uploader)

    def get_or_create_wikimedia_source(self):
        source, created = Source.objects.get_or_create(
            name="Wikimedia Commons",
            defaults={
                "url": "https://commons.wikimedia.org/",
                "description": "A media repository that is part of the Wikimedia Foundation.",
                "public": True,
            },
        )
        return source

    def get_collection_info(self, initial_query=None):
        print("\n=== Wikimedia Commons Collection Import ===")
        category = input(f"Wikimedia Category (e.g., 'Images from Brück & Sohn'): ")
        query = input(f"Search filter query within category [{initial_query or 'riverside'}]: ") or (
                    initial_query or "riverside")

        # Build a pseudo-slug for tracking
        slug = f"wm-{category.lower().replace(' ', '-')}"

        name = input(f"Collection display name: ")
        default_desc = f"Images from Wikimedia Category: {category}, filtered for {query}."
        description = input(f"Description [{default_desc}]: ") or default_desc

        return {
            "category": category,
            "query": query,
            "name": name,
            "description": description,
            "slug": slug
        }

    def create_collection_if_not_exist(self, source, info):
        collection, created = Collection.objects.get_or_create(
            source=source,
            name=info['name'],
            defaults={
                "url": f"https://commons.wikimedia.org/wiki/Category:{info['category'].replace(' ', '_')}",
                "description": info['description'],
                "public": False,
            }
        )
        return collection

    def fetch_wikimedia_page(self, query, category, continue_token=None):
        api_url = "https://commons.wikimedia.org/w/api.php"
        search_str = f'{query} incategory:"{category}"'

        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": search_str,
            "gsrnamespace": 6,
            "gsrlimit": 50,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|timestamp",
        }

        if continue_token:
            params.update(continue_token)

        response = requests.get(api_url, params=params)
        response.raise_for_status()
        return response.json()

    def handle_import(self, collection, info, max_items, r2_uploader):
        processed_count = 0
        continue_token = None

        with tqdm(total=max_items or 1000, desc="Importing") as pbar:
            while True:
                data = self.fetch_wikimedia_page(info['query'], info['category'], continue_token)
                pages = data.get("query", {}).get("pages", {}).values()

                for page in pages:
                    if max_items and processed_count >= max_items:
                        return

                    img_info = page.get("imageinfo", [{}])[0]
                    metadata = img_info.get("extmetadata", {})

                    # LoC Style Record Building
                    ref = str(page.get("pageid"))
                    if Image.objects.filter(ref=ref).exists():
                        continue

                    file_url = img_info.get("url")
                    title = page.get("title", "").replace("File:", "")

                    # Metadata Extraction
                    description = metadata.get("ImageDescription", {}).get("value", "")
                    # Clean HTML tags often found in Wikimedia descriptions
                    description = re.sub('<[^<]+?>', '', description)

                    creator = metadata.get("Artist", {}).get("value", "")
                    creator = re.sub('<[^<]+?>', '', creator)

                    original_date = metadata.get("DateTimeOriginal", {}).get("value", "")
                    # Placeholder for the parse_loc_date style logic if needed
                    edtf_date = None

                    try:
                        image = Image.objects.create(
                            collection=collection,
                            title=title[:255],
                            permalink=file_url,
                            ref=ref,
                            original_url=f"https://commons.wikimedia.org/entity/M{ref}",
                            description=description,
                            creator=creator,
                            original_date=original_date,
                            edtf_date=edtf_date,
                        )

                        # R2 Upload & Tiling
                        r2_url = r2_uploader.upload_original(image.id, file_url, in_tqdm=True)
                        if r2_url:
                            Image.objects.filter(pk=image.id).update(permalink=r2_url)
                            generate_iiif_tiles.delay(image.id)

                        processed_count += 1
                        pbar.update(1)
                        sleep(POLITE_WAIT_SECS)

                    except Exception as e:
                        print(f"Error importing {title}: {e}")

                continue_token = data.get("continue")
                if not continue_token:
                    break