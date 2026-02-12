import requests
import time
import logging

class GeocodingEngine:
    """
    Engine for Reverse Geocoding and Static Map generation.
    Uses OpenStreetMap (Nominatim) for geocoding.
    """
    
    def __init__(self, user_agent="DDD-Tachograph-Reader/1.0 (contact@example.com)"):
        self.user_agent = user_agent
        self.base_url = "https://nominatim.openstreetmap.org/reverse"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.cache = {}

    def reverse_geocode(self, lat, lon):
        """
        Convert coordinates to a human-readable location name.
        Nominatim usage policy: 1 request per second.
        """
        cache_key = (round(lat, 3), round(lon, 3))
        if cache_key in self.cache:
            return self.cache[cache_key]

        params = {
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "addressdetails": 1,
            "zoom": 10  # City level
        }
        
        try:
            # Respect rate limit
            time.sleep(1.1)
            response = self.session.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                address = data.get("address", {})
                city = address.get("city") or address.get("town") or address.get("village") or address.get("suburb") or address.get("municipality")
                country_code = address.get("country_code", "").upper()
                
                if city and country_code:
                    result = f"{city}, {country_code}"
                elif country_code:
                    result = country_code
                else:
                    # Fallback to display_name or parts of it
                    display_name = data.get("display_name", "")
                    if display_name:
                        parts = display_name.split(",")
                        result = ", ".join(parts[:2]) if len(parts) > 1 else display_name
                    else:
                        result = "Unknown"
                
                self.cache[cache_key] = result
                return result
        except Exception as e:
            logging.error(f"Geocoding error: {e}")
        
        return "N/A"

    def generate_static_map_url(self, locations, width=600, height=400):
        """
        Generates a Static Map URL using OpenStreetMap-based static map services.
        Example using staticmap.openstreetmap.de or similar.
        For this implementation, we'll use a public service or a placeholder logic.
        """
        if not locations:
            return None
            
        # Extract main points (Start, End, and some intermediate if many)
        points = []
        if len(locations) > 0:
            points.append(locations[0]) # Start
        if len(locations) > 2:
            # Add a middle point
            points.append(locations[len(locations)//2])
        if len(locations) > 1:
            points.append(locations[-1]) # End

        # Using static-maps.yandex.ru or staticmap.openstreetmap.de
        # Let's use a simple format for a static map URL (OSM-Static-Maps style)
        markers = []
        for i, p in enumerate(points):
            label = "S" if i == 0 else ("E" if i == len(points)-1 else "M")
            markers.append(f"marker-{label}|{p['latitude']},{p['longitude']}")
        
        # Example URL (Note: specific services might require registration, using a generic logic)
        # We'll return a Google-compatible or OSM-compatible string
        base_url = "https://static-maps.yandex.ru/1.x/?"
        pt_param = "~".join([f"{p['longitude']},{p['latitude']},pm2rdm" for p in points])
        map_url = f"{base_url}l=map&pt={pt_param}&size={width},{height}&lang=en_US"
        
        return map_url

def process_locations_with_geocoding(results):
    """
    Enrich the results with geocoding information.
    """
    engine = GeocodingEngine()
    locations = results.get("locations", [])
    
    # To avoid hitting the API too much, we limit to key locations or unique coordinates
    unique_coords = {}
    for loc in locations:
        key = (round(loc["latitude"], 3), round(loc["longitude"], 3))
        if key not in unique_coords:
            unique_coords[key] = loc

    # Geocode unique locations
    for key, loc in unique_coords.items():
        loc["location_name"] = engine.reverse_geocode(loc["latitude"], loc["longitude"])
    
    # Map back to all locations
    for loc in locations:
        key = (round(loc["latitude"], 3), round(loc["longitude"], 3))
        loc["location_name"] = unique_coords[key].get("location_name", "N/A")
    
    # Generate map URL
    results["metadata"]["static_map_url"] = engine.generate_static_map_url(locations)
    
    return results
