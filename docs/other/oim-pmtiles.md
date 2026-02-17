# Generating PMTiles from OIM

This is an opinionated guide for generating PMTiles for historical map mosaics.
We'll use OldInsuranceMaps.net (OIM) as our example, but the same process could be used for any maps.

## Dependencies

Please install [gdal](https://gdal.org/en/stable/download.html) and [uv](https://docs.astral.sh/uv/getting-started/installation/).

## Creating Your Environment

Make a folder for this project.
In your terminal, use the `cd` command to navigate to your project directory.

Run these `uv` commands to get the project going and install the `rio-pmtiles` tool.

```
uv init
uv add rio-pmtiles
```

## Build a VRT

If you have multiple maps you'd like to merge, you can do that by creating a VRT, which is essentially a file which represents a merged set of raster files.

Here is a command for a VRT from all `.tif` files in the current directory:

```
gdalbuildvrt out.vrt *.tif
```

For example, the first two 1952 Richmond Sanborn volumes can be found [here](https://oldinsurancemaps.net/map/sanborn09064_016) and [here](https://oldinsurancemaps.net/map/sanborn09064_017).
You can download mosaic GeoTIFF files for these volumes under the Summary > Mosaic Download & Web Services menu.
Those URLs are [`https://s3.us-central-1.wasabisys.com/oldinsurancemaps/uploaded/mosaics/sanborn09064_016-main-content__2024-07-27__znVEUT.tif`](https://s3.us-central-1.wasabisys.com/oldinsurancemaps/uploaded/mosaics/sanborn09064_016-main-content__2024-07-27__znVEUT.tif) and [`https://s3.us-central-1.wasabisys.com/oldinsurancemaps/uploaded/mosaics/sanborn09064_017-main-content__2024-07-27__QAY0tK.tif`](https://s3.us-central-1.wasabisys.com/oldinsurancemaps/uploaded/mosaics/sanborn09064_017-main-content__2024-07-27__QAY0tK.tif), respectively.
You could download these two files and create a VRT using the above command.

## Generate the PMTiles

```
uv run rio pmtiles --zoom-levels 4..20 --rgba out.vrt output.pmtiles
```

4 is way zoomed out, probably an appropriate lowest value for most any map.
As you add finer and finer zoom levels (20 is pretty fine), you will be generating tons and tons of tiny tiles which may or may not increase the quality of your map as the user zooms closer.
In other words, at some point you will run out of detail in your source map, and generating tinier tiles will only increase the size of your `.pmtiles` file.
So, please experiment with this setting.
Perhaps zoom 18 is good enough, or maybe you'll see better quality by generating tiles at zoom 21.

`--rgba` means respect transparency, and don't fill in around the edges of your map with a black background.

## So You Ran Out of Memory

Some of these TIFFs are really big, and for big tiles rio-pmtiles will try to read the whole thing into memory to create a nice tile that shows the whole area.
This means you can run out of memory very quickly!
Fret not, we have a trick for that:

```
gdal_translate -of COG \
  -co COMPRESS=DEFLATE \
  -co PREDICTOR=2 \
  -co OVERVIEW_RESAMPLING=AVERAGE \
  -co NUM_THREADS=ALL_CPUS \
  -co BIGTIFF=YES \
  -co BLOCKSIZE=512 \
  out.vrt merged_cog.tif
```

Then, run the `rio-pmtiles` command above but pass in `merged_cog.tif` instead of `out.vrt`.

As you might imagine, `gdal_translate` has many options and there may be better settings for your use-case.
I encourage you to read [the docs](https://gdal.org/en/stable/programs/gdal_translate.html) for that command, get in touch with us if you run into any issues, and contribute your learnings to this guide.
Thanks!
