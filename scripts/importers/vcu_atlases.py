#!/usr/bin/env -S uv run --script
#
# /// script
# dependencies = [
#   "requests"
# ]
# ///

import argparse
import os
import re
import requests
import time

# NOTE! It just so happens that the Beers and Baist Atlases have the actual maps
#  on pages 5-25. This is hardcoded in, but should be changed if the script is
#  adapted for other sources.

parser = argparse.ArgumentParser(description="Download Beers or Baist Atlas images from VCU and create index.")
parser.add_argument('--atlas', type=str, default="beers", help="Which atlas to download (beers or baist)")
args = parser.parse_args()

# Create directory if it doesn't exist
directory_path = f"{args.atlas}_atlas_rva"

if not os.path.exists(directory_path):
    os.makedirs(directory_path)
    print(f"Directory '{directory_path}' created.")

    if not os.path.exists(f"{directory_path}/{directory_path}_filelist.csv"):
      with open(f"{directory_path}/{directory_path}_filelist.csv", "w") as f:
        f.write("path,id\n")
      print(f"Index '{directory_path}_filelist.csv' created.")
else:
    print(f"Directory '{directory_path}' already exists.")

if not os.path.exists(f"{directory_path}/images"):
    os.makedirs(f"{directory_path}/images")
    print(f"Directory '{directory_path}/images' created.")
else:
    print(f"Directory '{directory_path}/images' already exists.")


# Download images
atlas_base = f"https://scholarscompass.vcu.edu/context/{args.atlas}_images/article"
    

for i in range(4, 25):
    url = f"{atlas_base}/10{i:02d}/type/native/viewcontent"
    response = requests.get(
        url, 
        timeout = 30
    )

    if response.status_code == 200:
        img_path = f"{directory_path}/images/{args.atlas}_{i:02d}.jpg"
        with open(img_path, "wb") as f:
            f.write(response.content)

        print(f"Downloaded {url} to {img_path}")

        item_info = requests.get(
            url = f"https://scholarscompass.vcu.edu/{args.atlas}_images/{i+1}",
            headers = {
              "User-Agent": "MapRVA Georeference Tool (https://github.com/MapRVA/georeference-tool)"
            },
            timeout = 30
        )
        
        item_id = re.findall(
            r'Plate Number</h2>\s*<p>(.*?)</p>',
            item_info.text
        )

        if not item_id:
            item_id = "key"
        else:
            item_id = item_id[0]


        with open(f"{directory_path}/{directory_path}_filelist.csv", "a") as f:
            f.write(f'{img_path},{item_id}\n')
        
        print(f"Added metadata to {directory_path}/{directory_path}_filelist.csv")
        
    else:
        print(f"Failed to download {url}")

    time.sleep(1)