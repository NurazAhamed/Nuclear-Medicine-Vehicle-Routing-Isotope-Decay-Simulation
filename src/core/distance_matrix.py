import os
import requests
import time
import math
import numpy as np
import polyline
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

TFNSW_API_TOKEN = os.getenv("TFNSW_API_TOKEN")

@dataclass
class Location:
    lat: float
    lon: float

class TfNSWClient:
    BASE_URL = "https://api.transport.nsw.gov.au/v1/tp"

    def __init__(self, token: Optional[str] = None):
        self.token = token or TFNSW_API_TOKEN
        self.headers = {'Authorization': f'apikey {self.token}'}

    def get_trip_duration(self, origin: Location, destination: Location) -> Optional[float]:
        if not self.token:
            return None
        url = f"{self.BASE_URL}/trip"
        params = {
            'outputFormat': 'rapidJSON', 'coordOutputFormat': 'EPSG:4326',
            'depArrMacro': 'dep', 'itdDate': '20250101', 'itdTime': '1200',
            'type_origin': 'coord',
            'name_origin': f"{origin.lon}:{origin.lat}:EPSG:4326",
            'type_destination': 'coord',
            'name_destination': f"{destination.lat},{destination.lon}",
            'calcNumberOfTrips': 1
        }
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'journeys' in data and len(data['journeys']) > 0:
                    return 45.0
            return None
        except Exception:
            return None

    def fetch_incidents(self):
        pass


def get_haversine_distance(origin: Location, destination: Location) -> float:
    R = 6371
    dlat = math.radians(destination.lat - origin.lat)
    dlon = math.radians(destination.lon - origin.lon)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(origin.lat)) * math.cos(math.radians(destination.lat)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calculate_duration_fallback(distance_km: float, tier: int) -> float:
    if tier in [1, 2]:
        speed, multiplier = 50.0, 1.4
    else:
        speed, multiplier = 80.0, 1.0
    return (distance_km * multiplier / speed) * 60


def generate_distance_matrix(locations: List[dict], client: Optional[TfNSWClient] = None) -> np.ndarray:
    n = len(locations)
    matrix = np.zeros((n, n))
    use_api = client is not None and client.token is not None
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            origin = Location(locations[i]['lat'], locations[i]['lon'])
            dest = Location(locations[j]['lat'], locations[j]['lon'])
            dest_tier = locations[j]['tier']
            duration = None
            if use_api:
                time.sleep(0.25)
                duration = client.get_trip_duration(origin, dest)
            if duration is None:
                dist = get_haversine_distance(origin, dest)
                duration = calculate_duration_fallback(dist, dest_tier)
            matrix[i][j] = duration
    return matrix


# ═══════════════════════════════════════════════════════════════
#  OSRM Road-Network Services
# ═══════════════════════════════════════════════════════════════

def snap_to_road(lat: float, lon: float) -> Dict:
    """Uses OSRM nearest service to snap a coordinate to the road network."""
    try:
        url = f"http://router.project-osrm.org/nearest/v1/driving/{lon},{lat}"
        r = requests.get(url, params={'number': 1}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data['code'] == 'Ok' and data.get('waypoints'):
                wp = data['waypoints'][0]
                return {
                    'lat': wp['location'][1],
                    'lon': wp['location'][0],
                    'distance_m': wp['distance'],
                    'name': wp.get('name', '')
                }
    except Exception as e:
        print(f"Road snap failed: {e}")
    return {'lat': lat, 'lon': lon, 'distance_m': 0, 'name': ''}


def _is_segment_near_point(origin: Location, dest: Location,
                            point_lat: float, point_lon: float,
                            radius_km: float = 2.0) -> bool:
    for i in range(11):
        t = i / 10.0
        lat = origin.lat + (dest.lat - origin.lat) * t
        lon = origin.lon + (dest.lon - origin.lon) * t
        if get_haversine_distance(Location(lat, lon), Location(point_lat, point_lon)) < radius_km:
            return True
    return False


def _calculate_detour_waypoint(origin: Location, dest: Location,
                                avoid_lat: float, avoid_lon: float) -> Location:
    dx = dest.lat - origin.lat
    dy = dest.lon - origin.lon
    px, py = -dy, dx
    mag = math.sqrt(px * px + py * py)
    if mag == 0:
        return Location(avoid_lat + 0.04, avoid_lon)
    px /= mag
    py /= mag
    offset = 0.045  # ~5km
    wp1 = Location(avoid_lat + px * offset, avoid_lon + py * offset)
    wp2 = Location(avoid_lat - px * offset, avoid_lon - py * offset)
    mid = Location((origin.lat + dest.lat) / 2, (origin.lon + dest.lon) / 2)
    d1 = get_haversine_distance(wp1, mid)
    d2 = get_haversine_distance(wp2, mid)
    return wp2 if d1 < d2 else wp1


def fetch_osrm_route_data(origin: Location, dest: Location,
                           avoid_point: Optional[Dict[str, float]] = None) -> Dict:
    """
    Core OSRM function: returns duration (minutes) AND geometry.
    If avoid_point is set and the route passes near it, injects a detour waypoint.
    This is the single source of truth for both matrix building and geometry fetching.
    """
    try:
        use_detour = False
        detour_wp = None

        if avoid_point:
            if _is_segment_near_point(origin, dest, avoid_point['lat'], avoid_point['lon']):
                use_detour = True
                detour_wp = _calculate_detour_waypoint(
                    origin, dest, avoid_point['lat'], avoid_point['lon'])

        if use_detour and detour_wp:
            coords = (f"{origin.lon},{origin.lat};"
                      f"{detour_wp.lon},{detour_wp.lat};"
                      f"{dest.lon},{dest.lat}")
            radiuses = "unlimited;50;unlimited"  # 50m snap radius for detour waypoint
        else:
            coords = f"{origin.lon},{origin.lat};{dest.lon},{dest.lat}"
            radiuses = None

        url = f"http://router.project-osrm.org/route/v1/driving/{coords}"
        params = {'overview': 'full', 'geometries': 'polyline'}
        if radiuses:
            params['radiuses'] = radiuses

        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data['code'] == 'Ok' and data['routes']:
                route = data['routes'][0]
                return {
                    'duration_min': route['duration'] / 60.0,
                    'distance_km': route['distance'] / 1000.0,
                    'geometry': polyline.decode(route['geometry']),
                    'detoured': use_detour
                }
    except Exception as e:
        print(f"OSRM route data failed ({origin.lat:.3f},{origin.lon:.3f} -> "
              f"{dest.lat:.3f},{dest.lon:.3f}): {e}")

    # Fallback
    dist = get_haversine_distance(origin, dest)
    return {
        'duration_min': calculate_duration_fallback(dist, 1),
        'geometry': [(origin.lat, origin.lon), (dest.lat, dest.lon)],
        'distance_km': dist,
        'detoured': False
    }


def fetch_route_geometry(origin: Location, dest: Location,
                         avoid_point: Optional[Dict[str, float]] = None
                         ) -> List[Tuple[float, float]]:
    """Convenience wrapper — returns only the geometry."""
    return fetch_osrm_route_data(origin, dest, avoid_point)['geometry']
