import os

# Directory holding the exported IR bundle (text.xml/bin, vision.xml/bin,
# tokenizer + preprocessor configs, metadata.json). Baked into the release
# image; bind-mounted in the dev compose stack.
MODEL_DIR = os.getenv("CLIP_MODEL_DIR", "/app/model")

# OpenVINO device for each tower. The text tower stays on CPU everywhere so
# query vectors are identical across GPU and CPU-only deployments. AUTO picks
# the GPU for the vision tower when one is present, otherwise CPU.
TEXT_DEVICE = os.getenv("CLIP_TEXT_DEVICE", "CPU")
VISION_DEVICE = os.getenv("CLIP_VISION_DEVICE", "AUTO")

# Compiled-kernel cache. Hardware/driver specific, so it belongs on an
# emptyDir/PV, never in the image. Empty string disables caching.
CACHE_DIR = os.getenv("CLIP_CACHE_DIR", "")

# Reject request bodies larger than this on /embed/image.
MAX_IMAGE_BYTES = int(os.getenv("CLIP_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
