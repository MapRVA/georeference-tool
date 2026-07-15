import json
import threading
from io import BytesIO
from pathlib import Path

import numpy as np
import openvino as ov
from PIL import Image
from transformers import CLIPImageProcessor, CLIPTokenizerFast


class ClipEncoder:
    """
    Both CLIP towers compiled with OpenVINO, plus tokenizer/preprocessing.

    Each tower keeps one persistent infer request guarded by a lock: with the
    LATENCY hint the device runs a single stream anyway, and FastAPI calls us
    from a thread pool, so concurrent requests simply queue on the lock.
    """

    def __init__(self, model_dir, text_device, vision_device, cache_dir=""):
        model_dir = Path(model_dir)
        self.meta = json.loads((model_dir / "metadata.json").read_text())

        core = ov.Core()
        if cache_dir:
            core.set_property({"CACHE_DIR": cache_dir})
        props = {"PERFORMANCE_HINT": "LATENCY"}

        self._text = core.compile_model(model_dir / "text.xml", text_device, props)
        self._vision = core.compile_model(
            model_dir / "vision.xml", vision_device, props
        )
        self._text_req = self._text.create_infer_request()
        self._vision_req = self._vision.create_infer_request()
        self._text_lock = threading.Lock()
        self._vision_lock = threading.Lock()

        self._tokenizer = CLIPTokenizerFast.from_pretrained(model_dir)
        # The slow (PIL/numpy) processor: exact parity with the export-time
        # preprocessing without needing torch at runtime.
        self._preprocess = CLIPImageProcessor.from_pretrained(model_dir)

    def devices(self):
        """Actual execution devices, for /info."""
        result = {}
        for name, compiled in (("text", self._text), ("vision", self._vision)):
            try:
                result[name] = compiled.get_property("EXECUTION_DEVICES")
            except RuntimeError:
                result[name] = "unknown"
        return result

    def encode_text(self, text):
        tokens = self._tokenizer(
            [text],
            padding="max_length",
            max_length=self.meta["context_length"],
            truncation=True,
            return_tensors="np",
        )
        input_ids = tokens["input_ids"].astype(np.int64)
        with self._text_lock:
            result = self._text_req.infer({0: input_ids})
        return _normalize(next(iter(result.values()))[0])

    def encode_image(self, data):
        with Image.open(BytesIO(data)) as img:
            return self.encode_pil(img.convert("RGB"))

    def encode_pil(self, img):
        pixel_values = self._preprocess(images=img, return_tensors="np")[
            "pixel_values"
        ].astype(np.float32)
        with self._vision_lock:
            result = self._vision_req.infer({0: pixel_values})
        return _normalize(next(iter(result.values()))[0])

    def warmup(self):
        self.encode_text("warmup")
        self.encode_pil(Image.new("RGB", (64, 64)))


def _normalize(vector):
    vector = vector.astype(np.float32)
    return (vector / np.linalg.norm(vector)).tolist()
