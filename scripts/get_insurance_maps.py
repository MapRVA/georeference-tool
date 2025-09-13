import requests
import re
import json
import os

# Load or fetch data
if os.path.exists("insurance_maps.json"):
    with open("insurance_maps.json", "r") as f:
        data = json.load(f)
else:
    response = requests.get("https://oldinsurancemaps.net/viewer/richmond-va/")
    html = response.text
    match = re.search(r'<script id="viewer-props" type="application/json">(.*?)</script>', html, re.DOTALL)
    data = json.loads(match.group(1))
    with open("insurance_maps.json", "w") as f:
        json.dump(data, f)

# Extract data and save to new JSON
layers = []
for map_item in data['MAPS']:
    if map_item["main_layerset"]['mosaic_cog_url'].strip() != "":
        if not map_item["hidden"]:
            layers.append({
                'title': map_item['title'],
                'year': map_item['year'],
                'mosaic_url': map_item['main_layerset']['mosaic_cog_url']
            })

with open("insurance_layers.json", "w") as f:
    json.dump(layers, f, indent=2)
