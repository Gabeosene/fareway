import json
import urllib.request
import urllib.parse
from math import radians, cos, sin, asin, sqrt

# Configuration
OVERPASS_URL = "http://overpass-api.de/api/interpreter"
# Bounding Box for Budapest Center (Strict Downtown)
BBOX = "47.47,19.02,47.53,19.08"

QUERY = f"""
[out:json][timeout:45];
(
  way["highway"~"primary|secondary"]({BBOX});
);
out body;
>;
out skel qt;
"""

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 # Radius of earth in kilometers. Use 3956 for miles
    return c * r

def fetch_osm_data():
    print("Fetching data from OSM...")
    data = urllib.parse.urlencode({'data': QUERY}).encode('utf-8')
    req = urllib.request.Request(OVERPASS_URL, data=data)
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())

def process_osm_data(data):
    nodes = {}
    for element in data['elements']:
        if element['type'] == 'node':
            nodes[element['id']] = (element['lat'], element['lon'])

    links = []
    
    # Process Ways
    for element in data['elements']:
        if element['type'] == 'way':
            # Skip if minimal tags
            tags = element.get('tags', {})
            name = tags.get('name', f"Road {element['id']}")
            highway = tags.get('highway', None)
            railway = tags.get('railway', None)
            
            # Determine Type & Capacity
            l_type = "road"
            capacity = 1000
            price = 200
            
            if railway == "subway":
                l_type = "transit"
                capacity = 10000
                price = 350
                name = f"Metro: {name}"
            elif highway == "primary":
                capacity = 3000
                price = 300
            elif highway == "trunk":
                capacity = 5000
                price = 400
            elif highway == "secondary":
                capacity = 1500
                price = 200

            # Construct Geometry
            coords = []
            if 'nodes' in element:
                for n_id in element['nodes']:
                    if n_id in nodes:
                        coords.append(nodes[n_id])
            
            # Calculate Length just for fun (or capacity scaling?)
            # For now, let's just create the link
            
            if len(coords) > 1:
                link = {
                    "id": f"osm_{element['id']}",
                    "name": name,
                    "capacity": capacity,
                    "base_price_huf": price,
                    "type": l_type,
                    "coordinates": coords
                }
                links.append(link)

    print(f"Processed {len(links)} links.")
    return links

def main():
    try:
        raw_data = fetch_osm_data()
        links = process_osm_data(raw_data)
        
        # Load template config
        with open('demo_config.json', 'r', encoding='utf-8') as f:
            full_config = json.load(f)
        
        # Replace network
        full_config['network']['links'] = links
        full_config['simulation']['initial_flow'] = {} # Clear init flow as IDs changed
        
        # Save
        with open('full_city_config.json', 'w', encoding='utf-8') as f:
            json.dump(full_config, f, indent=2, ensure_ascii=False)
            
        print("Success! Saved to 'full_city_config.json'")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
