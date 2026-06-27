from io import BytesIO
from pathlib import Path

import requests
from django.core.management.base import BaseCommand
from PIL import Image as PILImage
from PIL import ImageOps

from images.models import Image
from images.tasks import process_image
from images.utils import R2Uploader, R2UploaderError, to_rgb


class Command(BaseCommand):
    help = "Generate WEBP thumbnails from images in the database (500px longest dimension, preserving aspect ratio)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            type=str,
            default="thumbnails",
            help="Directory to save thumbnails (default: thumbnails)",
        )
        parser.add_argument(
            "--quality",
            type=int,
            default=85,
            help="WEBP quality (1-100, default: 85)",
        )
        parser.add_argument(
            "--image-ids",
            type=str,
            help="Comma-separated list of specific image IDs to process",
        )
        parser.add_argument(
            "--collection-id",
            type=int,
            help="Only process images from a specific collection ID",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Timeout for downloading images in seconds (default: 30)",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Regenerate thumbnails for all images, even if they already have thumbnails",
        )
        parser.add_argument(
            "--no-upload-to-r2",
            action="store_true",
            help="Skip uploading thumbnails to R2 storage (default is to upload)",
        )
        parser.add_argument(
            "--save-local",
            action="store_true",
            help="Save thumbnails locally (in addition to R2 upload)",
        )

    def handle(self, *args, **options):
        output_dir = options["output_dir"]
        quality = options["quality"]
        timeout = options["timeout"]
        refresh = options["refresh"]
        no_upload_to_r2 = options["no_upload_to_r2"]
        save_local = options["save_local"]

        # Upload to R2 by default, unless --no-upload-to-r2 is specified
        upload_to_r2 = not no_upload_to_r2

        # Initialize R2 uploader if requested
        r2_uploader = None
        if upload_to_r2:
            try:
                r2_uploader = R2Uploader()
                self.stdout.write(self.style.SUCCESS("R2 uploader initialized"))
            except R2UploaderError as e:
                self.stdout.write(self.style.ERROR(f"Failed to initialize R2: {e}"))
                return

        # Create output directory if saving locally
        if save_local:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            self.stdout.write(f"Output directory: {output_dir}")

        # Get images to process
        images_queryset = Image.objects.all()

        # Filter by collection if provided
        if options["collection_id"]:
            collection_id = options["collection_id"]
            images_queryset = images_queryset.filter(collection_id=collection_id)
            self.stdout.write(f"Filtering to collection ID: {collection_id}")

        # Filter by specific IDs if provided
        if options["image_ids"]:
            try:
                image_ids = [int(id.strip()) for id in options["image_ids"].split(",")]
                images_queryset = images_queryset.filter(id__in=image_ids)
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(
                        "Invalid image IDs format. Use comma-separated integers."
                    )
                )
                return

        # By default, skip images that already have thumbnails (unless --refresh is set)
        if not refresh:
            images_queryset = images_queryset.filter(thumbnail__isnull=True)
            self.stdout.write(
                "Skipping images that already have thumbnails (use --refresh to regenerate all)"
            )

        total_images = images_queryset.count()

        if total_images == 0:
            self.stdout.write(self.style.WARNING("No images found to process."))
            return

        self.stdout.write(f"Processing {total_images} images...")

        processed_count = 0
        skipped_count = 0
        failed_count = 0

        for image in images_queryset:
            # Legacy images (pre-versioned-assets) have no generation directory
            # to write into. Delegate to process_image, which will migrate
            # them (bumping asset_generation 0 -> 1) as part of generating a
            # versioned thumbnail.
            if r2_uploader and image.asset_generation == 0:
                process_image.delay(image.id)
                self.stdout.write(
                    f"Queued process_image for legacy image {image.id} (asset_generation=0)"
                )
                processed_count += 1
                continue

            thumbnail_key = self.get_thumbnail_key(image.id, image.asset_generation)

            self.stdout.write(f"Processing image {image.id}: {image.permalink}")
            self.stdout.write(f"  Thumbnail key: {thumbnail_key}")

            try:
                # Download image
                pil_image = self.download_image(image.permalink, timeout)
                if pil_image is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Failed to download image {image.id}: {image.permalink}"
                        )
                    )
                    failed_count += 1
                    continue

                # Generate thumbnail
                thumbnail = self.create_thumbnail(pil_image, quality)

                # Convert thumbnail to bytes
                thumbnail_bytes = BytesIO()
                thumbnail.save(thumbnail_bytes, "WEBP", quality=quality)
                thumbnail_bytes.seek(0)

                # Upload to R2 if requested
                if r2_uploader:
                    try:
                        public_url = r2_uploader.upload_file_content(
                            thumbnail_bytes.read(),
                            thumbnail_key,
                            content_type="image/webp",
                            overwrite=refresh,
                        )
                        self.stdout.write(
                            self.style.SUCCESS(f"Uploaded to R2: {public_url}")
                        )

                        # Update the thumbnail URL via .update() to skip the
                        # post_save signal, which would queue process_image
                        # and (for any image that needs work) bump
                        # asset_generation. Writing in-place at the current
                        # generation is intentional — no CDN cache bust.
                        Image.objects.filter(pk=image.id).update(thumbnail=public_url)

                        # Reset BytesIO for potential local save
                        thumbnail_bytes.seek(0)
                    except R2UploaderError as e:
                        self.stdout.write(
                            self.style.ERROR(f"Failed to upload to R2: {e}")
                        )
                        failed_count += 1
                        continue

                # Save locally if requested
                if save_local:
                    output_path = Path(output_dir) / f"image_{image.id}_thumbnail.webp"
                    with open(output_path, "wb") as f:
                        f.write(thumbnail_bytes.read())
                    self.stdout.write(
                        self.style.SUCCESS(f"Saved locally: {output_path}")
                    )

                processed_count += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error processing image {image.id}: {str(e)}")
                )
                failed_count += 1

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("THUMBNAIL GENERATION COMPLETE")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Processed: {processed_count}")
        self.stdout.write(f"Skipped: {skipped_count}")
        self.stdout.write(f"Failed: {failed_count}")
        self.stdout.write(f"Total: {total_images}")

    def get_thumbnail_key(self, image_id: int, generation: int) -> str:
        """
        Generate the versioned thumbnail key for an image at its current
        asset generation.

        Example:
            image_id=42, generation=3 -> images/42/3/thumbnail.webp
        """
        return f"images/{image_id}/{generation}/thumbnail.webp"

    def download_image(self, url: str, timeout: int = 30):
        """Download an image from URL and return PIL Image"""
        try:
            response = requests.get(url, timeout=timeout, stream=True)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("image/"):
                self.stdout.write(
                    self.style.WARNING(f"URL does not return an image: {url}")
                )
                return None

            # Load image
            image_data = BytesIO(response.content)
            pil_image = to_rgb(ImageOps.exif_transpose(PILImage.open(image_data)))

            return pil_image

        except requests.RequestException as e:
            self.stdout.write(self.style.WARNING(f"Failed to download {url}: {str(e)}"))
            return None
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Failed to process image from {url}: {str(e)}")
            )
            return None

    def create_thumbnail(self, img: PILImage.Image, quality: int = 85):
        """Create a thumbnail with 500px longest dimension, preserving aspect ratio"""
        max_dimension = 500

        # Get current dimensions
        width, height = img.size

        # Calculate scaling factor based on longest dimension
        if width > height:
            # Width is longest - scale based on width
            scale_factor = max_dimension / width
        else:
            # Height is longest (or equal) - scale based on height
            scale_factor = max_dimension / height

        # Calculate new dimensions
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)

        # Resize with high quality
        img_thumb = img.resize((new_width, new_height), PILImage.LANCZOS)

        return img_thumb
