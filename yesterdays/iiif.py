import logging
import os
import tempfile

import pyvips
import requests

from images.utils import R2Uploader

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/ld+json",
}


def generate_and_upload_iiif_tiles(source_url, r2_tiles_prefix):
    """Generate IIIF 3.0 tiles from an image URL and upload them to R2.

    Downloads the image from *source_url*, produces a full tile pyramid with
    pyvips ``dzsave(layout="iiif3")``, and uploads every generated file to R2
    under *r2_tiles_prefix* (e.g. ``"images/42/tiles"``).

    Returns ``(width, height)`` of the source image.
    """
    uploader = R2Uploader()

    # pyvips dzsave appends the output directory's basename to the ``id``
    # value written into info.json.  We want info.json to contain
    # ``{public_base}/{r2_tiles_prefix}`` so we pass the *parent* of the
    # prefix as ``id`` and name the output directory after the last path
    # component.
    r2_parent = "/".join(r2_tiles_prefix.split("/")[:-1])
    dir_basename = r2_tiles_prefix.split("/")[-1]
    iiif_id_url = uploader.get_public_url(r2_parent)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download the source image
        source_path = os.path.join(tmpdir, "source")
        resp = requests.get(source_url, timeout=120, stream=True)
        resp.raise_for_status()
        with open(source_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)

        # Generate IIIF tiles
        tile_dir = os.path.join(tmpdir, dir_basename)
        vimg = pyvips.Image.new_from_file(source_path, access="sequential")

        vimg.dzsave(
            tile_dir,
            layout="iiif3",
            tile_size=512,
            overlap=0,
            suffix=".jpg[Q=85]",
            id=iiif_id_url,
        )

        # Upload the tile tree to R2
        for root, _dirs, files in os.walk(tile_dir):
            for fname in files:
                local_path = os.path.join(root, fname)
                rel_path = os.path.relpath(local_path, tile_dir)
                key = f"{r2_tiles_prefix}/{rel_path}"
                file_ext = os.path.splitext(fname)[1].lower()
                content_type = CONTENT_TYPES.get(
                    file_ext, "application/octet-stream"
                )

                with open(local_path, "rb") as f:
                    uploader.upload_file_content(
                        f.read(),
                        key,
                        content_type=content_type,
                        overwrite=True,
                    )

        width, height = vimg.width, vimg.height

    logger.info(
        "IIIF tiles uploaded to %s (%dx%d)",
        r2_tiles_prefix,
        width,
        height,
    )
    return width, height
