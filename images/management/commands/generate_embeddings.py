"""
Django management command to generate CLIP embeddings for images.

Usage:
    python manage.py generate_embeddings [--batch-size 100] [--force] [--image-ids 1,2,3]
"""

import gc
from io import BytesIO
from itertools import islice
from pathlib import Path
from typing import Optional

import clip
import requests
import torch
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image as PILImage

from images.models import Image


class Command(BaseCommand):
    help = "Generate CLIP embeddings for images"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=32,
            help="Number of images to process in each batch (default: 32)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate embeddings for images that already have them",
        )
        parser.add_argument(
            "--image-ids",
            type=str,
            help="Comma-separated list of specific image IDs to process",
        )
        parser.add_argument(
            "--model-name",
            type=str,
            default="ViT-L/14@336px",
            help="CLIP model name to use (default: ViT-L/14@336px)",
        )
        parser.add_argument(
            "--device",
            type=str,
            choices=["auto", "cpu", "cuda"],
            default="auto",
            help="Device to use for processing (default: auto)",
        )

    def handle(self, *args, **options):
        self.setup_model(options)

        # Get images to process
        images_queryset = self.get_images_queryset(options)
        total_images = images_queryset.count()

        if total_images == 0:
            self.stdout.write(self.style.WARNING("No images found to process."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Processing {total_images} images in batches of {options['batch_size']}"
            )
        )

        # Process images in batches, iterating lazily
        batch_size = options["batch_size"]
        processed_count = 0
        failed_count = 0
        batch_num = 0

        iterator = images_queryset.iterator(chunk_size=batch_size)
        while batch_images := list(islice(iterator, batch_size)):
            batch_num += 1
            self.stdout.write(f"Processing batch {batch_num}...")

            batch_processed, batch_failed = self.process_batch(batch_images)
            processed_count += batch_processed
            failed_count += batch_failed

            self.stdout.write(
                f"Batch complete: {batch_processed} processed, {batch_failed} failed"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Embedding generation complete: {processed_count} processed, {failed_count} failed"
            )
        )

    def setup_model(self, options):
        """Initialize the CLIP model and preprocessing"""
        device = options["device"]
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model_name = options["model_name"]

        local_model_dir = Path("./models").absolute()

        self.stdout.write(f"Loading CLIP model {model_name}")
        self.model, self.preprocess = clip.load(
            model_name, device=device, download_root=local_model_dir
        )

        self.device = device
        self.stdout.write(f"Using device: {device}")

    def get_images_queryset(self, options):
        """Get the queryset of images to process"""
        queryset = Image.objects.only("id", "permalink", "embedding")

        # Filter by specific IDs if provided
        if options["image_ids"]:
            try:
                image_ids = [int(id.strip()) for id in options["image_ids"].split(",")]
                queryset = queryset.filter(id__in=image_ids)
            except ValueError:
                raise CommandError(
                    "Invalid image IDs format. Use comma-separated integers."
                )

        # Filter out images that already have embeddings unless --force is used
        if not options["force"]:
            queryset = queryset.filter(embedding__isnull=True)

        return queryset.order_by("id")

    def process_batch(self, batch_images) -> tuple[int, int]:
        """Process a batch of images and return (processed_count, failed_count)"""
        successful_images = []
        embeddings = []

        # Download and preprocess images
        for image in batch_images:
            try:
                pil_image = self.download_image(image.permalink)
                if pil_image is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Failed to download image {image.id}: {image.permalink}"
                        )
                    )
                    continue

                try:
                    preprocessed = self.preprocess(pil_image)
                finally:
                    pil_image.close()

                successful_images.append(image)
                embeddings.append(preprocessed)

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error processing image {image.id}: {str(e)}")
                )
                continue

        if not embeddings:
            return 0, len(batch_images)

        # Generate embeddings
        try:
            embeddings_tensor = torch.stack(embeddings).to(self.device)
            del embeddings

            with torch.no_grad():
                features = self.model.encode_image(embeddings_tensor)
                features /= features.norm(dim=-1, keepdim=True)

            # Convert to lists for database storage
            features_list = features.cpu().numpy().tolist()

            del embeddings_tensor, features
            if self.device == "cuda":
                torch.cuda.empty_cache()

            # Save to database
            with transaction.atomic():
                for image, embedding in zip(successful_images, features_list):
                    image.embedding = embedding
                    image.save(update_fields=["embedding"])

            return len(successful_images), len(batch_images) - len(successful_images)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error generating embeddings for batch: {str(e)}")
            )
            return 0, len(batch_images)
        finally:
            gc.collect()

    def download_image(self, url: str, timeout: int = 30) -> Optional[PILImage.Image]:
        """Download an image from URL and return PIL Image"""
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("image/"):
                self.stdout.write(
                    self.style.WARNING(f"URL does not return an image: {url}")
                )
                return None

            # Load image — .convert("RGB") copies pixel data, so we can
            # close the original immediately to free the BytesIO buffer.
            image_data = BytesIO(response.content)
            pil_image = PILImage.open(image_data).convert("RGB")
            image_data.close()

            return pil_image

        except requests.RequestException as e:
            self.stdout.write(self.style.WARNING(f"Failed to download {url}: {str(e)}"))
            return None
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Failed to process image from {url}: {str(e)}")
            )
            return None
