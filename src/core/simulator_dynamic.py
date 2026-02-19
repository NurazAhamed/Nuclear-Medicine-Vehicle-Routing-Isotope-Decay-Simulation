import logging
import json
import time
import math
import sys
import os
import io
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from typing import List

from src.core.optimizer import IsotopeOptimizer
from src.core.data_loader import Hospital, load_hospitals
from src.core.distance_matrix import generate_distance_matrix, TfNSWClient, get_haversine_distance, Location
from src.core.use_cases.decay_calculator import DecayCalculator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Simulator")

MIN_ACTIVITY_THRESHOLD = 0.25 
HALF_LIFE = 6.0
INITIAL_ACTIVITY = 100.0

class DynamicSimulator:
    def __init__(self):
        self.original_optimizer = IsotopeOptimizer()
        self.hospitals = self.original_optimizer.hospitals

    def interpolate_location(self, origin: Hospital, dest: Hospital, progress_fraction: float) -> Hospital:
        new_lat = origin.lat + (dest.lat - origin.lat) * progress_fraction
        new_lon = origin.lon + (dest.lon - origin.lon) * progress_fraction
        return Hospital(
            name=f"Van_Loc_EnRoute_{dest.name}",
            lat=new_lat,
            lon=new_lon,
            tier=0,
            type="Mobile"
        )
    
    def run_m5_scenario(self):
        logger.info("Initializing M5 'Black Swan' Scenario...")
        
        # 1. Baseline Solve
        logger.info("Solving initial baseline...")
        self.original_optimizer.solve_and_report()
        
        with open("output/routes.json", 'r') as f:
            routes_data = json.load(f)
            
        # 2. Identify Target Van
        target_vid = None
        target_route = None
        
        for r in routes_data:
             steps = r['steps']
             if len(steps) > 1 and "St George" in steps[0]['name']:
                     target_vid = r['vehicle_id']
                     target_route = r
                     break
        
        if target_vid is None:
            logger.info("Strict 'St George' route not found, picking first available Metro route.")
            for r in routes_data:
                if len(r['steps']) > 0 and r['steps'][0]['tier'] == 1:
                    target_vid = r['vehicle_id']
                    target_route = r
                    break
        
        if target_vid is None:
             logger.error("No suitable route found for simulation.")
             return

        # 3. Simulate T=45 min
        logger.info(f"Simulating T=45 min for Van {target_vid}...")
        
        first_stop = target_route['steps'][0]
        arrival_time = first_stop['arrival_time_min']
        
        current_loc = None
        next_dest_h = None
        next_dest_idx = 0
        
        if 45 < arrival_time:
            fraction = 45.0 / arrival_time
            origin_h = self.hospitals[0] # ANSTO
            dest_h = next(h for h in self.hospitals if h.name == first_stop['name'])
            current_loc = self.interpolate_location(origin_h, dest_h, fraction)
            next_dest_h = dest_h
            next_dest_idx = 0
        else:
            if len(target_route['steps']) > 1:
                prev_stop = target_route['steps'][0]
                next_stop = target_route['steps'][1]
                duration = next_stop['arrival_time_min'] - prev_stop['arrival_time_min']
                elapsed = 45 - prev_stop['arrival_time_min']
                fraction = elapsed / duration if duration > 0 else 0
                
                origin_h = next(h for h in self.hospitals if h.name == prev_stop['name'])
                dest_h = next(h for h in self.hospitals if h.name == next_stop['name'])
                
                current_loc = self.interpolate_location(origin_h, dest_h, fraction)
                next_dest_h = dest_h
                next_dest_idx = 1
            else:
                logger.warning("Route too short for T=45 simulation.")
                return

        logger.warning(f"BLACK SWAN: M5 Tunnel Closure detected at T=45! Ahead: {next_dest_h.name}")
        
        # 4. Scenario A: Ignorant System
        loc_dicts = [{"lat": current_loc.lat, "lon": current_loc.lon, "tier": 0}, 
                     {"lat": next_dest_h.lat, "lon": next_dest_h.lon, "tier": next_dest_h.tier}]
        matrix = generate_distance_matrix(loc_dicts, None)
        base_time = matrix[0][1]
        
        # 1000% Penalty as requested (10x)
        spiked_time = base_time * 10.0 
        
        ignorant_arrival_time = 45 + spiked_time
        ignorant_activity = DecayCalculator.calculate_remaining_activity(INITIAL_ACTIVITY, ignorant_arrival_time/60.0, HALF_LIFE)
        
        logger.info(f"Option A (Ignorant): Arrive {next_dest_h.name} at T={ignorant_arrival_time:.1f} min. Activity: {ignorant_activity:.2f}%")
        
        # 5. Scenario B: Intelligent System (Reroute)
        remaining_stops_names = [s['name'] for s in target_route['steps'][next_dest_idx:]]
        remaining_hospitals = [current_loc]
        for name in remaining_stops_names:
            h = next((x for x in self.hospitals if x.name == name), None)
            if h: remaining_hospitals.append(h)
            
        logger.info("Optimizer: Rerouting with penalty logic...")
        reroute_loc_dicts = [{"lat": h.lat, "lon": h.lon, "tier": h.tier} for h in remaining_hospitals]
        reroute_matrix = generate_distance_matrix(reroute_loc_dicts, None)
        
        # Apply Spike to next_dest (Index 1)
        reroute_matrix[0][1] = spiked_time
        
        reroute_optimizer = IsotopeOptimizer(hospitals_list=remaining_hospitals, custom_matrix=reroute_matrix)
        reroute_optimizer.num_vehicles = 1
        reroute_optimizer.vehicle_capacity = 10
        
        reroute_optimizer.solve_and_report()
        
        with open("output/routes.json", 'r') as f:
            reroute_data = json.load(f)
            
        intelligent_steps = reroute_data[0]['steps']
        intelligent_next_node = intelligent_steps[0]['name'] if intelligent_steps else "None"
        
        dropped = next_dest_h.name not in [s['name'] for s in intelligent_steps]
        
        logger.info(f"Option B (Intelligent): Next Stop -> {intelligent_next_node}")
        
        self.generate_simulation_log(ignorant_arrival_time, ignorant_activity, intelligent_steps, next_dest_h, dropped)
        self.plot_decay_curve(ignorant_arrival_time, next_dest_h.name)

    def generate_simulation_log(self, ignorant_time, ignorant_activity, intelligent_steps, target_hospital, dropped):
        log = f"""# Simulation Log: M5 Black Swan Event

## Scenario
*   **Event**: M5 Tunnel Closure (Traffic Spike) at T=45 min.
*   **Target**: {target_hospital.name} (Tier {target_hospital.tier}).
*   **Futility Threshold**: {MIN_ACTIVITY_THRESHOLD*100}% Activity.

## Comparison

### Option A: Ignorant System (Push Through)
*   **Arrival Time**: T={ignorant_time:.1f} min
*   **Activity**: {ignorant_activity:.2f} units
*   **Viable?**: {"YES" if ignorant_activity > MIN_ACTIVITY_THRESHOLD*100 else "NO (FUTILE)"}

### Option B: Intelligent System (AI Reroute)
*   **Decision**: {"ABANDON & REROUTE" if dropped else "PERSIST"}
*   **New Route**: {[s['name'] for s in intelligent_steps]}
"""
        with open("simulation_log.md", "w") as f:
            f.write(log)
        logger.info("Simulation Log generated: simulation_log.md")

    def plot_decay_curve(self, disrupted_arrival_time, hospital_name):
        t = np.linspace(0, disrupted_arrival_time + 60, 100) 
        lambda_val = math.log(2) / HALF_LIFE
        activity = INITIAL_ACTIVITY * np.exp(-lambda_val * (t / 60.0))
        
        plt.figure(figsize=(10, 6))
        plt.plot(t, activity, label='Isotope Decay (Tc-99m)', color='blue')
        plt.axvline(x=45, color='orange', linestyle='--', label='Disruption (T=45)')
        plt.axvline(x=disrupted_arrival_time, color='red', linestyle='-.', label=f'Ignorant Arrival (T={int(disrupted_arrival_time)})')
        plt.scatter([disrupted_arrival_time], [INITIAL_ACTIVITY * math.exp(-lambda_val * disrupted_arrival_time/60)], color='red')
        plt.axhline(y=MIN_ACTIVITY_THRESHOLD*100, color='gray', linestyle=':', label='Futility Threshold')
        
        plt.title(f"Decay Profile: Route to {hospital_name}")
        plt.xlabel("Time (minutes)")
        plt.ylabel("Activity (%)")
        plt.legend()
        plt.grid(True)
        plt.savefig("output/decay_plot.png")
        logger.info("Decay plot saved: output/decay_plot.png")

if __name__ == "__main__":
    sim = DynamicSimulator()
    sim.run_m5_scenario()
