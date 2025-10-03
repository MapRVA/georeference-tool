# /// script
# dependencies = [
#   "requests",
#   "time",
# ]
# ///

import os
import requests
import re
import time

# Create directory if it doesn't exist
directory_path = "beers_atlas_rva"

if not os.path.exists(directory_path):
    os.makedirs(directory_path)
    print(f"Directory '{directory_path}' created.")

    if not os.path.exists(f"{directory_path}/{directory_path}_filelist.csv"):
      with open(f"{directory_path}/{directory_path}_filelist.csv", "w") as f:
        f.write("path,section\n")
      print(f"Index '{directory_path}_filelist.csv' created.")
else:
    print(f"Directory '{directory_path}' already exists.")

if not os.path.exists(f"{directory_path}/images"):
    os.makedirs(f"{directory_path}/images")
    print(f"Directory '{directory_path}/images' created.")
else:
    print(f"Directory '{directory_path}/images' already exists.")


# Download images
beers_base = "https://scholarscompass.vcu.edu/context/beers_images/article"


for i in range(4, 25):
    url = f"{beers_base}/10{i:02d}/type/native/viewcontent"
    response = requests.get(
        url, 
        timeout = 30
    )

    if response.status_code == 200:
        img_path = f"{directory_path}/images/beers_{i:04d}.jpg"
        with open(img_path, "wb") as f:
            f.write(response.content)

        print(f"Downloaded {url} to {img_path}")

        item_info = requests.get(
            url = f"https://scholarscompass.vcu.edu/beers_images/{i+1}",
            headers = {
              "User-Agent": "MapRVA Georeference Tool (https://github.com/MapRVA/georeference-tool)"
            },
            timeout = 30
        )
        item_title = re.findall(r'<meta itemprop="name" content="(.*?)"',
                                item_info.text)


        with open(
            f"{directory_path}/{directory_path}_filelist.csv", "a") as f:
            f.write(f'{img_path},{re.sub(r".*_", "", item_title[0])}\n')
        
        print(f"Added metadata to {directory_path}/{directory_path}_filelist.csv")
        
    else:
        print(f"Failed to download {url}")

    time.sleep(1)