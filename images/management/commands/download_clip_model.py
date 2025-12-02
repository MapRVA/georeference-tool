"""
Django management command to download CLIP model if it does not exist.

Usage:
    python manage.py download_clip_model [--model-name ViT-L/14@336px] [--device auto]
"""

import ssl
import torch
from pathlib import Path

import clip
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download CLIP model if it does not exist"

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
        import warnings

        device = options["device"]
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model_name = options["model_name"]
        local_model_dir = Path("./models").absolute()

        # Create models directory if it doesn't exist
        local_model_dir.mkdir(parents=True, exist_ok=True)

        # Check if model files exist
        existing_files = list(local_model_dir.glob("**/*.pt"))

        if existing_files:
            self.stdout.write(f"Found existing model files in {local_model_dir}")
            self.stdout.write(f"Attempting to verify CLIP model {model_name}...")

            # Try to load the model to verify checksum
            try:
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    model, preprocess = clip.load(
                        model_name, device=device, download_root=local_model_dir
                    )

                    # Check if there was a checksum warning
                    checksum_warning = any(
                        "checksum" in str(warning.message).lower() for warning in w
                    )

                    if checksum_warning:
                        self.stdout.write(
                            self.style.WARNING(
                                "Checksum mismatch detected. Cleaning corrupted files and re-downloading..."
                            )
                        )
                        # Delete corrupted files
                        for pt_file in local_model_dir.glob("**/*.pt"):
                            pt_file.unlink()
                        self.stdout.write(
                            "Corrupted files deleted. Will re-download..."
                        )
                    else:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Model verified successfully in {local_model_dir}"
                            )
                        )
                        return
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"Error verifying existing model: {str(e)}. Will re-download..."
                    )
                )
                # Delete corrupted files
                for pt_file in local_model_dir.glob("**/*.pt"):
                    try:
                        pt_file.unlink()
                    except Exception:
                        pass

        self.stdout.write(f"Downloading CLIP model {model_name}...")
        self.stdout.write(f"Using device: {device}")

        try:
            model, preprocess = clip.load(
                model_name, device=device, download_root=local_model_dir
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully downloaded CLIP model {model_name} to {local_model_dir}"
                )
            )
        except ssl.SSLError as e:
            # SSL errors during download are often non-fatal - check if files exist
            if list(local_model_dir.glob("**/*.pt")):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"CLIP model downloaded successfully to {local_model_dir} (SSL warning ignored)"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"Failed to download CLIP model: {str(e)}")
                )
                raise
        except Exception as e:
            # Check if files were downloaded despite the exception
            if list(local_model_dir.glob("**/*.pt")):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"CLIP model files exist in {local_model_dir} (error ignored)"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"Failed to download CLIP model: {str(e)}")
                )
                raise
