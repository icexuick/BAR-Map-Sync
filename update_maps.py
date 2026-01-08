import requests
import py7zr
import re
import os
import shutil

# --- CONFIGURATIE ---
WEBFLOW_API_TOKEN = os.environ.get("WEBFLOW_API_TOKEN") # Haal uit environment variables
COLLECTION_ID = "JOUW_COLLECTION_ID_HIER" # Of ook via env var
# Controleer goed wat de field slugs zijn in Webflow (vaak alles lowercase met streepjes)
FIELD_MIN = "map-height-min"
FIELD_MAX = "map-height-max"
FIELD_DOWNLOAD_URL = "download-url" # De slug van je .sd7 link veld

HEADERS = {
    "Authorization": f"Bearer {WEBFLOW_API_TOKEN}",
    "accept-version": "2.0.0", # Webflow API v2
    "content-type": "application/json"
}

def get_maps_without_height():
    """Haalt alle items op uit Webflow CMS."""
    url = f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items"
    items_to_process = []
    
    # Let op: Webflow pagineert (max 100 items per call). 
    # Voor simpelheid hier even 1 call, voor prod moet je loopen met offset.
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"Error fetching items: {response.text}")
        return []

    data = response.json()
    
    for item in data.get('items', []):
        fields = item.get('fieldData', {})
        # Check of data al bestaat om dubbel werk te voorkomen
        has_min = fields.get(FIELD_MIN)
        has_max = fields.get(FIELD_MAX)
        
        if has_min is None or has_max is None:
            items_to_process.append(item)
            
    return items_to_process

def extract_map_info(sd7_url):
    """Download .sd7, pak mapinfo.lua, parse smf block."""
    temp_filename = "temp_map.sd7"
    
    try:
        # 1. Download bestand (stream om geheugen te sparen, maar schrijf naar disk voor 7z)
        print(f"Downloading {sd7_url}...")
        with requests.get(sd7_url, stream=True) as r:
            r.raise_for_status()
            with open(temp_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)

        # 2. Open 7z en zoek mapinfo.lua
        min_h, max_h = None, None
        
        if not py7zr.is_7zfile(temp_filename):
            print("Geen geldig 7z bestand (misschien normale zip?).")
            return None, None

        with py7zr.SevenZipFile(temp_filename, mode='r') as z:
            # We zoeken specifiek naar mapinfo.lua
            all_files = z.getnames()
            mapinfo_path = next((f for f in all_files if f.endswith('mapinfo.lua')), None)
            
            if mapinfo_path:
                content_dict = z.read([mapinfo_path])
                lua_content = content_dict[mapinfo_path].read().decode('utf-8', errors='ignore')
                
                # 3. Regex Parsing (Lua is lastig, maar we zoeken specifiek in de SMF tabel)
                # We zoeken eerst het SMF blok, en daarin de waardes.
                # Regex zoekt naar smf = { ... } en pakt de content.
                smf_block_match = re.search(r'smf\s*=\s*\{([^}]+)\}', lua_content, re.IGNORECASE | re.DOTALL)
                
                if smf_block_match:
                    smf_content = smf_block_match.group(1)
                    
                    # Zoek minheight en maxheight in het smf blok
                    min_match = re.search(r'minheight\s*=\s*([-\d\.]+)', smf_content, re.IGNORECASE)
                    max_match = re.search(r'maxheight\s*=\s*([-\d\.]+)', smf_content, re.IGNORECASE)
                    
                    if min_match: min_h = float(min_match.group(1))
                    if max_match: max_h = float(max_match.group(1))

    except Exception as e:
        print(f"Error processing map: {e}")
    finally:
        # Opruimen
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
    return min_h, max_h

def update_webflow_item(item_id, min_h, max_h):
    """Update het item in Webflow."""
    url = f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items/{item_id}"
    
    payload = {
        "fieldData": {
            FIELD_MIN: min_h,
            FIELD_MAX: max_h
        }
    }
    
    response = requests.patch(url, json=payload, headers=HEADERS)
    if response.status_code == 200:
        print(f"Succesvol geupdate: {item_id}")
    else:
        print(f"Update failed: {response.text}")

# --- MAIN LOOP ---
def main():
    items = get_maps_without_height()
    print(f"Gevonden maps om te updaten: {len(items)}")
    
    for item in items:
        url = item['fieldData'].get(FIELD_DOWNLOAD_URL)
        if not url: continue
        
        print(f"Verwerken: {item['fieldData'].get('name', 'Unknown')}")
        min_h, max_h = extract_map_info(url)
        
        if min_h is not None and max_h is not None:
            print(f"Gevonden: Min {min_h}, Max {max_h}")
            update_webflow_item(item['id'], min_h, max_h)
        else:
            print("Geen data gevonden in mapinfo.lua")

if __name__ == "__main__":
    main()