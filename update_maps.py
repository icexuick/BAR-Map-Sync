import requests
import py7zr
import re
import os
import shutil
import time

# --- CONFIGURATIE ---
WEBFLOW_API_TOKEN = "ecc5c96047196d316bf15f0965d58caf4bae19f8801093498651d99bc2f49064"
COLLECTION_ID = "6564c6553676389f8ba45aaf"
FIELD_MIN = "map-height-min"
FIELD_MAX = "map-height-max"
FIELD_DOWNLOAD_URL = "downloadurl"

HEADERS = {
    "Authorization": f"Bearer {WEBFLOW_API_TOKEN}",
    "accept-version": "2.0.0",
    "content-type": "application/json"
}

def get_maps_without_height():
    """Haalt items op uit Webflow waar nog geen hoogte data bij staat."""
    url = f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items"
    items_to_process = []
    offset = 0
    limit = 100
    
    print("Ophalen van CMS items uit Webflow...")
    
    while True:
        params = {'limit': limit, 'offset': offset}
        try:
            response = requests.get(url, headers=HEADERS, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Error fetching items: {e}")
            break

        current_batch = data.get('items', [])
        if not current_batch:
            break

        print(f"   ...batch verwerkt (offset {offset})")

        for item in current_batch:
            fields = item.get('fieldData', {})
            # Check of data al bestaat (leeg veld is None)
            if fields.get(FIELD_MIN) is None or fields.get(FIELD_MAX) is None:
                items_to_process.append(item)
        
        if len(current_batch) < limit:
            break
            
        offset += limit
            
    return items_to_process

def extract_map_info(sd7_url):
    """
    Downloadt de map, pakt ALLEEN de mapinfo.lua in de root, 
    en haalt de min/max height eruit.
    """
    temp_archive = "temp_map.sd7"
    temp_extract_dir = "temp_extract"
    min_h, max_h = None, None
    
    # Opruimen vooraf
    if os.path.exists(temp_extract_dir):
        shutil.rmtree(temp_extract_dir)
    if os.path.exists(temp_archive):
        os.remove(temp_archive)
    
    try:
        # 1. Downloaden
        print(f"   -> Downloaden: {sd7_url}")
        with requests.get(sd7_url, stream=True) as r:
            r.raise_for_status()
            with open(temp_archive, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
        
        # 2. Archief openen
        if py7zr.is_7zfile(temp_archive):
            with py7zr.SevenZipFile(temp_archive, mode='r') as z:
                all_files = z.getnames()
                
                # --- DE FIX ---
                # We zoeken exact naar "mapinfo.lua". 
                # Als een bestand in een map zit, heet het "map/mapinfo.lua", dus dat matcht niet.
                target_file = None
                for f in all_files:
                    if f.lower() == "mapinfo.lua":
                        target_file = f
                        break
                
                if not target_file:
                    print("   -> GEEN mapinfo.lua in de root gevonden (submappen genegeerd).")
                    return None, None
                
                # 3. Uitpakken (alleen dat ene bestand)
                z.extract(targets=[target_file], path=temp_extract_dir)
                local_path = os.path.join(temp_extract_dir, target_file)
                
                # 4. Lezen en Parsen
                with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Regex om minheight en maxheight te vinden
                    # Zoekt naar: minheight = 100  of  minheight=100
                    min_match = re.search(r'minheight\s*=\s*([\d\.-]+)', content, re.IGNORECASE)
                    max_match = re.search(r'maxheight\s*=\s*([\d\.-]+)', content, re.IGNORECASE)
                    
                    if min_match:
                        min_h = float(min_match.group(1))
                    if max_match:
                        max_h = float(max_match.group(1))

    except Exception as e:
        print(f"   -> Fout bij verwerken map: {e}")
    finally:
        # Opruimen achteraf
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
        if os.path.exists(temp_archive):
            os.remove(temp_archive)

    return min_h, max_h

def update_webflow_item(item_id, min_h, max_h):
    """Stuurt de gevonden data naar Webflow."""
    url = f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items/{item_id}"
    
    payload = {
        "fieldData": {
            FIELD_MIN: min_h,
            FIELD_MAX: max_h
        }
    }
    
    try:
        response = requests.patch(url, json=payload, headers=HEADERS)
        if response.status_code == 200:
            print(f"   -> SUCCES: Item geupdate.")
        else:
            print(f"   -> UPDATE FAILED: {response.text}")
    except Exception as e:
        print(f"   -> API Error: {e}")

def main():
    items = get_maps_without_height()
    print(f"--- Start verwerking van {len(items)} maps ---\n")
    
    for item in items:
        name = item['fieldData'].get('name', 'Naamloos')
        url = item['fieldData'].get(FIELD_DOWNLOAD_URL)
        
        if not url:
            print(f"Overslaan: {name} (Geen download URL)")
            continue
            
        print(f"Verwerken: {name}")
        min_h, max_h = extract_map_info(url)
        
        if min_h is not None and max_h is not None:
            print(f"   -> Gevonden: Min {min_h} / Max {max_h}")
            update_webflow_item(item['id'], min_h, max_h)
        else:
            print("   -> Geen bruikbare hoogte data gevonden.")

        # Respecteer API rate limits
        time.sleep(1) 

if __name__ == "__main__":
    main()