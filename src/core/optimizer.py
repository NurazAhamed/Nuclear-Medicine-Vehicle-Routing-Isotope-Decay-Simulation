import json
import math
import os
from typing import List, Dict, Optional
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

from src.core.data_loader import load_hospitals, Hospital
from src.core.distance_matrix import (
    generate_distance_matrix, TfNSWClient, Location,
    fetch_osrm_route_data, snap_to_road,
    get_haversine_distance
)
from src.core.use_cases.decay_calculator import DecayCalculator

# ── Physics Constants ──
HALF_LIFE_TC99M = 6.0
INITIAL_ACTIVITY = 100.0
LAMBDA = math.log(2) / HALF_LIFE_TC99M  # ~0.1155 per hour

# ── Clinical Thresholds ──
FUTILITY_THRESHOLD = 35.0

# ── Financial Constants ──
DOSE_VALUE_AUD = 1500  # Base manufacturing + logistics cost per Tc-99m dose


class IsotopeOptimizer:
    def __init__(self, hospitals_file="hospitals.json", hospitals_list=None, custom_matrix=None):
        self.hospitals = hospitals_list if hospitals_list else load_hospitals(hospitals_file)
        self.depot_index = 0
        self.avoid_point = None
        self.snapped_incident = None

        if custom_matrix is not None:
            self.distance_matrix = custom_matrix
        else:
            client = TfNSWClient() if os.getenv("TFNSW_API_TOKEN") else None
            loc_dicts = [{"lat": h.lat, "lon": h.lon, "tier": h.tier} for h in self.hospitals]
            print("Generating distance matrix...")
            self.distance_matrix = generate_distance_matrix(loc_dicts, client)

        self.num_vehicles = 4
        self.vehicle_capacity = 10

    def create_data_model(self):
        data = {}
        data['time_matrix'] = self.distance_matrix
        data['num_vehicles'] = self.num_vehicles
        data['depot'] = self.depot_index
        data['demands'] = [0 if h.tier == 0 else 1 for h in self.hospitals]
        data['vehicle_capacities'] = [self.vehicle_capacity] * self.num_vehicles
        return data

    def is_segment_impacted(self, loc1, loc2, lat, lon, radius_km=2.0):
        for i in range(11):
            t = i / 10.0
            plat = loc1.lat + (loc2.lat - loc1.lat) * t
            plon = loc1.lon + (loc2.lon - loc1.lon) * t
            if get_haversine_distance(Location(plat, plon), Location(lat, lon)) < radius_km:
                return True
        return False

    # ═══════════════════════════════════════════════════════════════
    #  TASK 1: FORCED ROAD DIVERSION (Real OSRM Detour Durations)
    # ═══════════════════════════════════════════════════════════════
    def _apply_osrm_detour_durations(self, avoid_point):
        """
        Instead of setting matrix values to 999999 (which causes the solver to DROP nodes),
        query OSRM for the ACTUAL detour duration around the closure.
        The solver then works with realistic travel times and finds genuine alternative sequences.
        """
        incident_loc = Location(avoid_point['lat'], avoid_point['lon'])
        n = len(self.hospitals)
        rerouted = 0
        checked = 0

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue

                loc1 = Location(self.hospitals[i].lat, self.hospitals[i].lon)
                loc2 = Location(self.hospitals[j].lat, self.hospitals[j].lon)

                # Quick pre-filter: skip if both endpoints are >50km from incident
                d1 = get_haversine_distance(loc1, incident_loc)
                d2 = get_haversine_distance(loc2, incident_loc)
                if d1 > 50 and d2 > 50:
                    continue

                if self.is_segment_impacted(loc1, loc2, avoid_point['lat'], avoid_point['lon']):
                    checked += 1
                    # Get REAL alternative route duration from OSRM
                    route_data = fetch_osrm_route_data(loc1, loc2, avoid_point)
                    original = self.distance_matrix[i][j]
                    osrm_dur = route_data['duration_min']

                    # Use the longer of original vs detour to guarantee the impact is visible
                    # (prevents OSRM returning a shorter path than the haversine estimate)
                    self.distance_matrix[i][j] = max(original, osrm_dur)

                    if route_data['detoured']:
                        rerouted += 1

        print(f"  Checked {checked} arcs, rerouted {rerouted} with OSRM detour durations")

    def solve_and_report(self, avoid_point=None):
        self.avoid_point = avoid_point

        if avoid_point:
            # Step 1: Snap incident to road network for precision
            snapped = snap_to_road(avoid_point['lat'], avoid_point['lon'])
            self.snapped_incident = snapped
            print(f"Incident snapped to road: ({snapped['lat']:.6f}, {snapped['lon']:.6f}), "
                  f"{snapped['distance_m']:.1f}m from click, road: '{snapped['name']}'")

            # Step 2: Replace affected arcs with REAL detour durations (NOT 999999)
            snapped_point = {'lat': snapped['lat'], 'lon': snapped['lon']}
            self.avoid_point = snapped_point  # Use snapped coords for geometry later
            self._apply_osrm_detour_durations(snapped_point)

        data = self.create_data_model()

        manager = pywrapcp.RoutingIndexManager(
            len(data['time_matrix']), data['num_vehicles'], data['depot'])
        routing = pywrapcp.RoutingModel(manager)

        # ── Transit Callback ──
        def time_callback(from_index, to_index):
            return int(data['time_matrix'][manager.IndexToNode(from_index)]
                       [manager.IndexToNode(to_index)])

        transit_cb = routing.RegisterTransitCallback(time_callback)

        # ── Cost Callback (priority-weighted) ──
        def cost_callback(from_index, to_index):
            fn = manager.IndexToNode(from_index)
            tn = manager.IndexToNode(to_index)
            tt = data['time_matrix'][fn][tn]
            dest = self.hospitals[tn]
            pw = 1.0 if dest.tier == 0 else dest.get_priority_weight()
            return int(tt * (1.0 / pw) * 100)

        cost_cb = routing.RegisterTransitCallback(cost_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(cost_cb)

        # ── Capacity ──
        def demand_callback(from_index):
            return data['demands'][manager.IndexToNode(from_index)]

        demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_cb, 0, data['vehicle_capacities'], True, 'Capacity')

        # ── Time Dimension ──
        routing.AddDimension(transit_cb, 30, 1440, True, 'Time')
        time_dim = routing.GetDimensionOrDie('Time')

        for idx, h in enumerate(self.hospitals):
            if h.tier != 0:
                time_dim.CumulVar(manager.NodeToIndex(idx)).SetRange(0, 720)

        # ── Cardiac-Priority Soft Bounds ──
        for idx, h in enumerate(self.hospitals):
            if h.tier == 0:
                continue
            ni = manager.NodeToIndex(idx)
            if h.tier == 3:
                time_dim.SetCumulVarSoftUpperBound(ni, 120, 500)
            elif h.tier == 2:
                time_dim.SetCumulVarSoftUpperBound(ni, 180, 200)
            else:
                time_dim.SetCumulVarSoftUpperBound(ni, 240, 50)

        # ── Drop Penalties ──
        for idx, h in enumerate(self.hospitals):
            if idx == self.depot_index:
                continue
            penalty = {1: 50000, 2: 200000, 3: 1000000}.get(h.tier, 0)
            routing.AddDisjunction([manager.NodeToIndex(idx)], penalty)

        # ── Solve ──
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.time_limit.seconds = 10

        solution = routing.SolveWithParameters(params)
        if solution:
            self._export_solution(manager, routing, solution, data)
        else:
            print("No solution found!")

    # ═══════════════════════════════════════════════════════════════
    #  EXPORT: Recalculate ETA/Potency, Auto-Cancel, Financial Data
    # ═══════════════════════════════════════════════════════════════
    def _export_solution(self, manager, routing, solution, data):
        output_data = []
        time_dim = routing.GetDimensionOrDie('Time')

        fleet_total_potency = 0.0
        fleet_served = 0
        all_canceled = []

        for vid in range(data['num_vehicles']):
            index = routing.Start(vid)
            all_steps = []

            # ── Build ALL steps from solver ──
            while not routing.IsEnd(index):
                ni = manager.IndexToNode(index)
                h = self.hospitals[ni]
                arr_min = solution.Min(time_dim.CumulVar(index))
                hrs = arr_min / 60.0
                potency = INITIAL_ACTIVITY * math.exp(-LAMBDA * hrs)

                if potency >= 70:
                    triage = "OPTIMAL"
                elif potency >= FUTILITY_THRESHOLD:
                    triage = "DEGRADED"
                else:
                    triage = "FUTILE"

                all_steps.append({
                    "name": h.name, "tier": h.tier,
                    "arrival_time_min": arr_min,
                    "lat": h.lat, "lon": h.lon,
                    "potency": round(potency, 1),
                    "triage": triage
                })
                index = solution.Value(routing.NextVar(index))

            # End node (depot return)
            ni = manager.IndexToNode(index)
            h = self.hospitals[ni]
            all_steps.append({
                "name": h.name, "tier": h.tier,
                "arrival_time_min": solution.Min(time_dim.CumulVar(index)),
                "lat": h.lat, "lon": h.lon,
                "potency": 100.0, "triage": "DEPOT"
            })

            # ── Separate viable from futile ──
            viable, canceled = [], []
            for step in all_steps:
                if step['tier'] != 0 and step['potency'] < FUTILITY_THRESHOLD:
                    step['triage'] = 'CANCELED'
                    canceled.append(step)
                    all_canceled.append(step)
                else:
                    viable.append(step)
                    if step['tier'] != 0:
                        fleet_total_potency += step['potency']
                        fleet_served += 1

            # ── Fetch geometry for viable path (skipping canceled stops) ──
            geom = []
            if len(viable) > 1:
                for i in range(len(viable) - 1):
                    o = Location(viable[i]['lat'], viable[i]['lon'])
                    d = Location(viable[i + 1]['lat'], viable[i + 1]['lon'])
                    seg = fetch_osrm_route_data(o, d, avoid_point=self.avoid_point)['geometry']
                    if geom and seg and geom[-1] == seg[0]:
                        geom.extend(seg[1:])
                    else:
                        geom.extend(seg)

            # ── Per-Van Financial Calculations ──
            van_stops = [s for s in viable if s['tier'] != 0]
            van_preserved = sum((s['potency'] / 100.0) * DOSE_VALUE_AUD for s in van_stops)
            van_waste = sum(((100 - s['potency']) / 100.0) * DOSE_VALUE_AUD for s in van_stops)
            # Canceled deliveries = 100% waste
            canceled_waste = len(canceled) * DOSE_VALUE_AUD
            van_waste += canceled_waste
            van_mission = (len(van_stops) + len(canceled)) * DOSE_VALUE_AUD

            avg_pot = sum(s['potency'] for s in van_stops) / len(van_stops) if van_stops else 0

            output_data.append({
                "vehicle_id": vid,
                "steps": viable,
                "canceled": canceled,
                "geometry": geom,
                "avg_potency": round(avg_pot, 1),
                "financial": {
                    "mission_value": round(van_mission, 0),
                    "preserved_value": round(van_preserved, 0),
                    "waste_value": round(van_waste, 0)
                }
            })

        # ── Fleet Analytics ──
        fleet_avg = fleet_total_potency / fleet_served if fleet_served > 0 else 0
        doses_saved = sum(1 for r in output_data for s in r['steps'] if s['tier'] != 0 and s['potency'] >= 60)
        cardiac_ready = sum(1 for r in output_data for s in r['steps'] if s['tier'] != 0 and s['potency'] >= 70)

        total_mission = fleet_served * DOSE_VALUE_AUD + len(all_canceled) * DOSE_VALUE_AUD
        total_preserved = sum(r['financial']['preserved_value'] for r in output_data)
        total_waste = sum(r['financial']['waste_value'] for r in output_data)

        payload = {
            "routes": output_data,
            "analytics": {
                "fleet_avg_potency": round(fleet_avg, 1),
                "fleet_total_potency": round(fleet_total_potency, 1),
                "fleet_stops_served": fleet_served,
                "incident_active": self.avoid_point is not None,
                "snapped_road": self.snapped_incident.get('name', '') if self.snapped_incident else '',
                "clinical_outcomes": {
                    "doses_saved": doses_saved,
                    "cardiac_ready": cardiac_ready,
                    "avoided_waste_count": len(all_canceled),
                    "avoided_waste_cost": len(all_canceled) * DOSE_VALUE_AUD,
                    "canceled_missions": [
                        {"name": c['name'], "potency": c['potency'], "tier": c['tier'],
                         "original_eta_min": c['arrival_time_min']}
                        for c in all_canceled
                    ]
                },
                "financial": {
                    "dose_value": DOSE_VALUE_AUD,
                    "total_mission_value": round(total_mission, 0),
                    "total_preserved_value": round(total_preserved, 0),
                    "total_waste_value": round(total_waste, 0)
                }
            }
        }

        os.makedirs("output", exist_ok=True)
        with open("output/routes.json", "w") as f:
            json.dump(payload, f, indent=2)

        print(f"Exported: {fleet_served} served, {len(all_canceled)} canceled, "
              f"Avg: {fleet_avg:.1f}%, Cardiac: {cardiac_ready}, "
              f"Value preserved: ${total_preserved:,.0f}")


if __name__ == "__main__":
    IsotopeOptimizer().solve_and_report()
