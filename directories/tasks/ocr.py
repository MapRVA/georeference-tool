import base64
import json
import logging
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pytesseract
import requests
from celery import shared_task
from django.conf import settings
from PIL import Image

from images.utils import R2Uploader
from yesterdays.iiif import generate_and_upload_iiif_tiles

from ..models import Page

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    ignore_result=True,
    time_limit=1800,
    soft_time_limit=1500,
)
def generate_iiif_tiles(self, page_id):
    page = Page.objects.select_related("directory").get(pk=page_id)

    Page.objects.filter(pk=page_id).update(
        tile_status=Page.TileStatus.PROCESSING,
        tile_error="",
    )

    try:
        r2_prefix = f"directory/{page.uuid}/iiif"
        width, height = generate_and_upload_iiif_tiles(
            source_url=page.image_url,
            r2_tiles_prefix=r2_prefix,
        )

        Page.objects.filter(pk=page_id).update(
            tile_status=Page.TileStatus.COMPLETE,
            width=width,
            height=height,
        )
        logger.info(
            "IIIF tiles generated for page %s (%dx%d)",
            page.uuid,
            width,
            height,
        )

    except Exception as exc:
        logger.exception("Failed to generate IIIF tiles for page %s", page.uuid)
        Page.objects.filter(pk=page_id).update(
            tile_status=Page.TileStatus.FAILED,
            tile_error=str(exc),
        )
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=0,
    ignore_result=True,
    time_limit=300,
    soft_time_limit=240,
)
def run_page_ocr(self, page_id, prompt, model_identifier):
    page = Page.objects.select_related("directory").get(pk=page_id)

    logger.info("OCR for page %s using model %s", page.uuid, model_identifier)

    Page.objects.filter(pk=page_id).update(ocr_status="processing", ocr_error="")

    try:
        result = _do_page_ocr(page, prompt, model_identifier)
        Page.objects.filter(pk=page_id).update(
            ocr_status="complete",
            ocr_error="",
            ocr_raw=json.dumps(result, ensure_ascii=False),
        )
    except Exception as exc:
        logger.exception("OCR failed for page %s", page.uuid)
        Page.objects.filter(pk=page_id).update(ocr_status="failed", ocr_error=str(exc))
        raise self.retry(exc=exc)


def _detect_skew(pil_img, max_angle=5.0, step=0.5):
    """
    Detect the skew angle of a page image using projection profile variance.

    Tries rotations from -max_angle to +max_angle in increments of `step`,
    and returns the angle that maximizes variance of the horizontal projection
    (sharpest text line separation = correct orientation).

    Returns the angle in degrees to pass to PIL Image.rotate() to deskew.
    Returns 0.0 if the image is already straight.
    """
    # Work on a grayscale PIL image so rotation fillcolor is always scalar
    gray_pil = pil_img.convert("L") if pil_img.mode != "L" else pil_img
    binary = (np.array(gray_pil) < 128).astype(np.uint8)

    best_angle = 0.0
    best_variance = np.var(binary.sum(axis=1).astype(np.float64))

    steps = int(max_angle / step)
    for i in range(-steps, steps + 1):
        angle = i * step
        if angle == 0.0:
            continue
        rotated = gray_pil.rotate(
            angle,
            resample=Image.BICUBIC,
            expand=False,
            fillcolor=255,
        )
        rot_binary = (np.array(rotated) < 128).astype(np.uint8)
        variance = np.var(rot_binary.sum(axis=1).astype(np.float64))
        if variance > best_variance:
            best_variance = variance
            best_angle = angle

    return best_angle


def _rotate_bbox_to_original(x, y, w, h, skew_angle, img_width, img_height):
    """
    Map a bounding box from deskewed coordinates back to the original
    (skewed) image space.

    When we deskew by rotating the image by `skew_angle` degrees, Tesseract
    produces bounding boxes in that rotated space. To map them back we rotate
    each corner by -skew_angle around the image center, then take the
    axis-aligned bounding box of the result.

    Returns (x, y, w, h) in original image coordinates.
    """
    if skew_angle == 0.0:
        return x, y, w, h

    cx, cy = img_width / 2.0, img_height / 2.0
    angle_rad = math.radians(-skew_angle)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    rotated = []
    for px, py in corners:
        dx, dy = px - cx, py - cy
        rx = dx * cos_a - dy * sin_a + cx
        ry = dx * sin_a + dy * cos_a + cy
        rotated.append((rx, ry))

    xs = [p[0] for p in rotated]
    ys = [p[1] for p in rotated]
    return int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))


def _find_column_splits(image, margin_pct=0.05, min_depth=0.30):
    """
    Detect column gutters using valley detection on the vertical projection.

    Instead of looking for near-zero whitespace (which fails on aged paper),
    this finds points that are significantly lower than their neighbors on
    both sides — the signature of a column gutter even when it contains
    noise, stains, or bleed-through.

    Args:
        image: 2D uint8 numpy array (grayscale, from _to_grayscale)
        margin_pct: fraction of width to ignore on each edge
        min_depth: minimum average depth (0-1) for a valley to be a split.
            Depth is measured as the fractional drop from neighboring regions.

    Returns:
        List of x-coordinates for column split points.
    """
    gray = image if image.ndim == 2 else np.mean(image, axis=2)
    binary = (gray < 128).astype(np.uint8)
    projection = binary.sum(axis=0).astype(np.float64)

    # Smooth to reduce line-level noise
    kernel = np.ones(30) / 30
    smoothed = np.convolve(projection, kernel, mode="same")

    width = len(smoothed)
    margin = int(width * margin_pct)

    # For each x, compare against offset neighbor windows on both sides.
    # The offset avoids including the valley itself in the neighbor average.
    neighbor_dist = 40
    neighbor_width = 100

    candidates = []
    for x in range(margin, width - margin):
        left_start = max(margin, x - neighbor_dist - neighbor_width)
        left_end = max(margin, x - neighbor_dist)
        right_start = min(width - margin, x + neighbor_dist)
        right_end = min(width - margin, x + neighbor_dist + neighbor_width)
        if left_end <= left_start or right_end <= right_start:
            continue

        left_avg = smoothed[left_start:left_end].mean()
        right_avg = smoothed[right_start:right_end].mean()
        val = smoothed[x]

        if left_avg > 0 and right_avg > 0:
            left_depth = 1.0 - val / left_avg
            right_depth = 1.0 - val / right_avg
            avg_depth = (left_depth + right_depth) / 2.0
            # Must be below both sides and deep enough on average
            if left_depth > 0.05 and right_depth > 0.05 and avg_depth >= min_depth:
                candidates.append((x, avg_depth))

    if not candidates:
        return []

    # Cluster adjacent candidates and pick the deepest point in each
    clusters = []
    current = [candidates[0]]
    for c in candidates[1:]:
        if c[0] - current[-1][0] <= 30:
            current.append(c)
        else:
            clusters.append(current)
            current = [c]
    clusters.append(current)

    return [max(cluster, key=lambda c: c[1])[0] for cluster in clusters]


def _split_into_columns(pil_img, min_col_fraction=0.15):
    """
    Use XY-Cut vertical projection to detect column gutters and split
    the image into columns. Returns a list of dicts with keys:
      - crop: PIL Image for the column
      - x_offset: pixel offset of the crop within the original image

    Splits that would produce a column narrower than min_col_fraction
    of the image width are discarded.
    """

    # Convert image to grayscale
    # Helps handle 1-bit pixel values in some input images
    image = np.array(pil_img.convert("L"))

    # Detect vertical splits in image
    splits = _find_column_splits(image)

    # Miniumum width (in px) of detected columns to keep
    min_col_width = pil_img.width * min_col_fraction

    # Filter out splits that would create tiny columns
    boundaries = [0] + splits + [image.shape[1]]
    filtered = [0]
    for b in boundaries[1:]:
        if b - filtered[-1] >= min_col_width:
            filtered.append(b)
        else:
            # Merge this narrow region into the previous column
            pass
    if filtered[-1] != image.shape[1]:
        filtered[-1] = image.shape[1]

    columns = []
    for i in range(len(filtered) - 1):
        x0, x1 = filtered[i], filtered[i + 1]
        crop = pil_img.crop((x0, 0, x1, pil_img.height))
        columns.append({"crop": crop, "x_offset": x0})

    return columns


def _tesseract_lines(pil_img, dpi=300):
    """Run Tesseract on a single image and return raw line records."""
    data = pytesseract.image_to_data(
        pil_img,
        config=f"--oem 1 --psm 1 --dpi {dpi}",
        output_type=pytesseract.Output.DICT,
    )

    lines = {}
    for i in range(len(data["text"])):
        if data["level"][i] != 5:
            continue
        text = data["text"][i].strip()
        conf = int(data["conf"][i])
        if not text or conf < 0:
            continue

        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y, w, h = (
            data["left"][i],
            data["top"][i],
            data["width"][i],
            data["height"][i],
        )

        if key not in lines:
            lines[key] = {
                "block": data["block_num"][i],
                "words": [text],
                "confs": [conf],
                "x": x,
                "y": y,
                "x2": x + w,
                "y2": y + h,
            }
        else:
            entry = lines[key]
            entry["words"].append(text)
            entry["confs"].append(conf)
            entry["x"] = min(entry["x"], x)
            entry["y"] = min(entry["y"], y)
            entry["x2"] = max(entry["x2"], x + w)
            entry["y2"] = max(entry["y2"], y + h)

    return sorted(lines.values(), key=lambda e: (e["y"], e["x"]))


def _extract_lines(pil_img, dpi=300):
    """
    Deskew the image, detect columns via XY-Cut, run Tesseract on each
    column separately, then merge results with coordinates mapped back
    to the original (possibly skewed) image.
    """
    img_width, img_height = pil_img.size

    # Step 1: Detect and correct skew
    #
    # Convert to grayscale for all Tesseract processing — this ensures
    # 1-bit, palette, RGBA, etc. all work correctly with rotation and
    # binarization.  The original pil_img is never modified.
    work_img = pil_img.convert("L") if pil_img.mode != "L" else pil_img

    skew_angle = _detect_skew(work_img)
    if skew_angle != 0.0:
        work_img = work_img.rotate(
            skew_angle,
            resample=Image.BICUBIC,
            expand=False,
            fillcolor=255,
        )
        logger.info("Deskewed by %.1f° for Tesseract", skew_angle)

    # Step 2: Detect columns on the deskewed image
    columns = _split_into_columns(work_img)
    logger.info(
        "XY-Cut detected %d column(s) at splits %s (image %dx%d, skew=%.1f°)",
        len(columns),
        [col["x_offset"] for col in columns],
        work_img.width,
        work_img.height,
        skew_angle,
    )

    # Step 3: Run Tesseract on each column crop
    all_lines = []
    for i, col in enumerate(columns):
        x_offset = col["x_offset"]
        raw_lines = _tesseract_lines(col["crop"], dpi=dpi)
        logger.info(
            "Column %d (x_offset=%d, width=%d): %d lines",
            i,
            x_offset,
            col["crop"].width,
            len(raw_lines),
        )
        for entry in raw_lines:
            # Map from column-local coords to deskewed full-image coords
            entry["x"] += x_offset
            entry["x2"] += x_offset
            all_lines.append(entry)

    # Step 4: Rotate bounding boxes back to original image coordinates
    if skew_angle != 0.0:
        for entry in all_lines:
            dw = entry["x2"] - entry["x"]
            dh = entry["y2"] - entry["y"]
            ox, oy, ow, oh = _rotate_bbox_to_original(
                entry["x"],
                entry["y"],
                dw,
                dh,
                skew_angle,
                img_width,
                img_height,
            )
            entry["x"] = ox
            entry["y"] = oy
            entry["x2"] = ox + ow
            entry["y2"] = oy + oh

    # Sort column-first (by x) then top-to-bottom (by y) so line numbers
    # read naturally: left column top-to-bottom, then right column.
    all_lines.sort(key=lambda e: (e["x"], e["y"]))

    return [
        {
            "line": idx,
            "block": entry["block"],
            "text": " ".join(entry["words"]),
            "conf": round(float(np.mean(entry["confs"])), 1),
            "x": entry["x"],
            "y": entry["y"],
            "w": entry["x2"] - entry["x"],
            "h": entry["y2"] - entry["y"],
        }
        for idx, entry in enumerate(all_lines, start=1)
    ]


def _do_page_ocr(page, prompt, model_identifier, openrouter_timeout=120):
    """
    OCR pipeline for a single directory page:

    1. Download the original image from R2.
    2. Run Tesseract to extract line-level text with bounding boxes.
    3. Substitute the {{LINES}} placeholder in the prompt with the
       Tesseract output (line number + text only, no coordinates).
    4. Send the prompt AND the full image to an LLM via OpenRouter.
       The LLM returns structured JSON, where each entry includes a
       "lines" field listing which Tesseract line numbers it used.
    5. Match the "lines" references back to Tesseract's bounding boxes,
       computing a combined rectangle that encompasses all matched lines.
    6. Return the final JSON (now enriched with x/y/w/h coordinates).
    """

    # Initialize R2 uploader
    uploader = R2Uploader()

    # Determine path of original image in R2
    ext = Path(page.original_filename).suffix
    source_key = f"directory/{page.uuid}/original{ext}"

    with TemporaryDirectory() as tmpdir:
        source_path = os.path.join(tmpdir, f"source{ext}")
        uploader.s3_client.download_file(uploader.bucket_name, source_key, source_path)

        # Base64-encode for the OpenRouter vision request later
        with open(source_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Run Tesseract to get line-level text and bounding boxes
        pil_img = Image.open(source_path)
        tesseract_lines = _extract_lines(pil_img)
        logger.info(
            "Tesseract extracted %d lines for page %s", len(tesseract_lines), page.uuid
        )

    # Inject Tesseract-extracted text into the prompt
    # Replaces "{{LINES}}" in prompt with line number and OCR'd text, as JSON list
    if "{{LINES}}" in prompt:
        lines_for_prompt = [
            {"line": line["line"], "text": line["text"]} for line in tesseract_lines
        ]
        prompt = prompt.replace(
            "{{LINES}}", json.dumps(lines_for_prompt, ensure_ascii=False)
        )

    # Send the hydrated prompt + image to the LLM via OpenRouter
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/jpeg")

    # Use json_object mode instead of json_schema to avoid grammar
    # compilation limits.  json_schema's constrained decoding creates
    # 2^N states for N optional fields; with 18 optional fields that
    # exceeds Anthropic's grammar size cap.  json_object guarantees
    # syntactically valid JSON while the prompt describes the schema.
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_identifier,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_data}",
                            },
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=openrouter_timeout,
    )
    response.raise_for_status()

    result = response.json()
    if "choices" not in result:
        logger.error("OpenRouter response body: %s", json.dumps(result))
        error_msg = result.get("error", {}).get("message", json.dumps(result))
        raise RuntimeError(f"OpenRouter error: {error_msg}")
    llm_content: str = result["choices"][0]["message"]["content"] or ""
    logger.info(
        "OpenRouter response for page %s: finish_reason=%s, content length=%d",
        page.uuid,
        result["choices"][0].get("finish_reason"),
        len(llm_content),
    )
    if not llm_content:
        logger.error("OpenRouter returned empty content: %s", json.dumps(result))

    # Strip markdown fences (```json ... ```) that some models add
    stripped = llm_content.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        llm_content = stripped.strip()

    # Parse the LLM output.  We handle both a top-level {"entries": [...]}
    # wrapper and a bare array for robustness.
    entries = []
    parse_error = ""
    try:
        parsed = json.loads(llm_content)
        if isinstance(parsed, dict):
            entries = parsed.get("entries", parsed.get("results", []))
        elif isinstance(parsed, list):
            entries = parsed
    except (json.JSONDecodeError, ValueError) as exc:
        parse_error = str(exc)
        logger.warning("LLM returned invalid JSON for page %s: %s", page.uuid, exc)

    # Match bounding boxes from Tesseract back into successfully parsed entries.
    # Each LLM entry has a "lines" list of Tesseract line numbers. We look up
    # their bounding boxes and compute the smallest rectangle that encompasses
    # all matched lines.
    if entries:
        line_lookup = {l["line"]: l for l in tesseract_lines}
        for entry in entries:
            if "lines" not in entry:
                continue
            matched = [line_lookup[n] for n in entry["lines"] if n in line_lookup]
            if matched:
                x = min(l["x"] for l in matched)
                y = min(l["y"] for l in matched)
                x2 = max(l["x"] + l["w"] for l in matched)
                y2 = max(l["y"] + l["h"] for l in matched)
                entry["x"] = x
                entry["y"] = y
                entry["w"] = x2 - x
                entry["h"] = y2 - y
                entry["conf"] = round(float(np.mean([l["conf"] for l in matched])), 1)

    logger.info("OCR returned %d entries for page %s", len(entries), page.uuid)

    # Return all pipeline artifacts as a structured dict
    #
    # This is stored in ocr_raw so the frontend can show each stage:
    #  - prompt: the hydrated prompt sent to the LLM
    #  - llm_response: the verbatim text returned by the LLM
    #  - entries: the final entries enriched with bounding boxes
    #  - parse_error: set if the LLM response wasn't valid JSON
    result = {
        "prompt": prompt,
        "llm_response": llm_content,
        "entries": entries,
    }
    if parse_error:
        result["parse_error"] = parse_error

    return result
