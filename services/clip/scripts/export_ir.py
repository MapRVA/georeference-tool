"""
One-time export of CLIP ViT-L/14@336px to an OpenVINO IR bundle.

Run from services/clip/ with the export dependency group:

    uv run --group export scripts/export_ir.py

Writes the IR models plus tokenizer/preprocessor configs into model/ (which
the dev compose stack bind-mounts directly), then packs them into a versioned
tarball whose URL and sha256 feed the release image build (see
.github/workflows/clip-service.yml). Upload the tarball to R2 and update the
workflow variables when publishing a new bundle.
"""

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

import numpy as np
import openvino as ov
import torch
import transformers
from transformers import CLIPModel, CLIPProcessor

# The HF re-packaging of the exact OpenAI checkpoint the corpus was built on.
MODEL_ID = "openai/clip-vit-large-patch14-336"
CONTEXT_LENGTH = 77
IMAGE_SIZE = 336


class TextTower(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids):
        return self.model.get_text_features(input_ids=input_ids)


class VisionTower(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, pixel_values):
        return self.model.get_image_features(pixel_values=pixel_values)


def export(out_dir, bundle_version):
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {MODEL_ID} …")
    model = CLIPModel.from_pretrained(MODEL_ID)
    model.eval()
    processor = CLIPProcessor.from_pretrained(MODEL_ID)

    print("Converting text tower …")
    example_ids = torch.zeros((1, CONTEXT_LENGTH), dtype=torch.int64)
    text_ov = ov.convert_model(TextTower(model), example_input=example_ids)
    text_ov.reshape([-1, CONTEXT_LENGTH])
    ov.save_model(text_ov, out_dir / "text.xml")

    print("Converting vision tower …")
    example_pixels = torch.zeros((1, 3, IMAGE_SIZE, IMAGE_SIZE), dtype=torch.float32)
    vision_ov = ov.convert_model(VisionTower(model), example_input=example_pixels)
    vision_ov.reshape([-1, 3, IMAGE_SIZE, IMAGE_SIZE])
    ov.save_model(vision_ov, out_dir / "vision.xml")

    processor.save_pretrained(out_dir)

    metadata = {
        "model_id": MODEL_ID,
        "bundle_version": bundle_version,
        "dim": model.config.projection_dim,
        "context_length": CONTEXT_LENGTH,
        "image_size": IMAGE_SIZE,
        "normalized": True,
        "exported_with": {
            "transformers": transformers.__version__,
            "torch": torch.__version__,
            "openvino": ov.__version__,
        },
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return model, processor


def verify(out_dir, model, processor):
    """Compare IR outputs against torch on sample inputs; drift should be ~0."""
    core = ov.Core()
    text_c = core.compile_model(out_dir / "text.xml", "CPU")
    vision_c = core.compile_model(out_dir / "vision.xml", "CPU")

    text = "a photograph of a city street with a monument"
    tokens = processor.tokenizer(
        [text],
        padding="max_length",
        max_length=CONTEXT_LENGTH,
        truncation=True,
        return_tensors="pt",
    )
    with torch.no_grad():
        torch_text = model.get_text_features(input_ids=tokens["input_ids"])
    ov_text = next(iter(text_c({0: tokens["input_ids"].numpy()}).values()))

    rng = np.random.default_rng(0)
    pixels = rng.random((1, 3, IMAGE_SIZE, IMAGE_SIZE), dtype=np.float32)
    with torch.no_grad():
        torch_vision = model.get_image_features(pixel_values=torch.from_numpy(pixels))
    ov_vision = next(iter(vision_c({0: pixels}).values()))

    for name, a, b in (
        ("text", torch_text.numpy()[0], ov_text[0]),
        ("vision", torch_vision.numpy()[0], ov_vision[0]),
    ):
        cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
        print(f"{name} tower torch↔OpenVINO cosine similarity: {cos:.6f}")
        if cos < 0.999:
            raise SystemExit(f"{name} tower drift too large ({cos}); aborting")


def pack(out_dir, bundle_version):
    tar_path = out_dir.parent / f"clip-vit-l14-336-ir-{bundle_version}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for path in sorted(out_dir.iterdir()):
            tar.add(path, arcname=path.name)
    digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    print(f"\nBundle: {tar_path}")
    print(f"Size:   {tar_path.stat().st_size / 1e6:.0f} MB")
    print(f"SHA256: {digest}")
    print(
        "\nUpload to R2, then set MODEL_BUNDLE_URL and MODEL_BUNDLE_SHA256 "
        "in .github/workflows/clip-service.yml"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).parent.parent / "model"
    )
    parser.add_argument("--bundle-version", default="v1")
    parser.add_argument(
        "--skip-pack", action="store_true", help="Only populate --out (for local dev)"
    )
    args = parser.parse_args()

    model, processor = export(args.out, args.bundle_version)
    verify(args.out, model, processor)
    if not args.skip_pack:
        pack(args.out, args.bundle_version)


if __name__ == "__main__":
    main()
