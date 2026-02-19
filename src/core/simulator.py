import logging
import json
import time
import math
import sys
import os
import numpy as np
from datetime import datetime, timedelta
from typing import List

# Add src to path - keeping for standalone execution if needed, but relative imports are preferred in package
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from src.core.optimizer import IsotopeOptimizer
from src.core.data_loader import Hospital, load_hospitals
from src.core.distance_matrix import generate_distance_matrix, TfNSWClient, get_haversine_distance, Location

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Simulator")

class TransportSimulator:
    def __init__(self):
        self.original_optimizer = IsotopeOptimizer()
        self.hospitals = self.original_optimizer.hospitals
        
    def interpolate_location(self, origin: Hospital, dest: Hospital, progress_fraction: float) -> Hospital:
        """Calculates current lat/lon based on progress."""
        new_lat = origin.lat + (dest.lat - origin.lat) * progress_fraction
        new_lon = origin.lon + (dest.lon - origin.lon) * progress_fraction
        return Hospital(
            name=f"Van_Loc_EnRoute_{dest.name}",
            lat=new_lat,
            lon=new_lon,
            tier=0, # Treated as source/depot for reroute
            type="Mobile"
        )
        
    def find_route_to_disrupt(self, routes_data):
        """Finds a route going to a Tier 3 hospital (e.g., Orange/Dubbo/Wagga)."""
        for route in routes_data:
            vehicle_id = route['vehicle_id']
            steps = route['steps']
            for i in range(len(steps) - 1):
                # Check if this leg goes to a Tier 3
                dest_name = steps[i+1]['name']
                dest_tier = steps[i+1]['tier']
                if dest_tier == 3:
                     logger.info(f"Targeting Vehicle {vehicle_id} en route to {dest_name} (Tier 3) for disruption.")
                     return vehicle_id, route
        return None, None

    def run_simulation(self):
        logger.info("Initializing Simulation...")
        
        # 1. Initial Solve
        logger.info("Solving initial Optimization Problem...")
        self.original_optimizer.solve_and_report()
        
        # Parse output for routes
        with open("output/routes.json", 'r') as f:
            routes_data = json.load(f)
            
        # 2. Pick target route
        target_vid, target_route = self.find_route_to_disrupt(routes_data)
        if target_vid is None:
            logger.error("No Tier 3 route found to disrupt. Aborting.")
            return

        # 3. Simulate Steps
        # Assuming departure is T=0
        # "Black Swan" at Hour 2 (120 mins)
        disruption_time_min = 120
        
        # Find where the van is at T=120
        steps = target_route['steps']
        current_node = None
        next_node = None
        
        # Naive simulation: Find the leg active at 120 min
        for i in range(len(steps) - 1):
            start_time = steps[i]['arrival_time_min']
            end_time = steps[i+1]['arrival_time_min']
            
            if start_time <= disruption_time_min < end_time:
                # Van is here
                origin_step = steps[i]
                dest_step = steps[i+1]
                
                # Calculate progress
                leg_duration = end_time - start_time
                elapsed = disruption_time_min - start_time
                fraction = elapsed / leg_duration if leg_duration > 0 else 0
                
                # Origin and Dest Objects
                origin_h = next(h for h in self.hospitals if h.name == origin_step['name'])
                dest_h = next(h for h in self.hospitals if h.name == dest_step['name'])
                
                current_van_loc = self.interpolate_location(origin_h, dest_h, fraction)
                
                logger.info(f"T=120min: Van {target_vid} is {(fraction*100):.1f}% along leg {origin_h.name} -> {dest_h.name}.")
                
                # 4. Trigger Black Swan
                self.trigger_reroute(target_vid, current_van_loc, steps[i+1:], origin_h, dest_h)
                break
        else:
            logger.warning("Van might have finished or hasn't started by T=120? Checking end state.")

    def trigger_reroute(self, vehicle_id, current_loc, remaining_steps, disrupted_origin, disrupted_dest):
        logger.warning(f"BLACK SWAN EVENT: Major closure detected on M5/Great Western Hwy between {disrupted_origin.name} and {disrupted_dest.name}!")
        logger.warning("Spiking travel time by 400%...")
        
        # 1. Construct Reroute Problem
        # New "Depot" is current_loc
        # Remaining destinations
        remaining_hospitals = [current_loc]
        
        # Map remaining steps to Hospital objects
        # Note: remaining_steps[0] is the immediate destination current leg is aiming for.
        # remaining_steps include the rest of the route.
        # We need to find these in the master list.
        for step in remaining_steps:
             # Be careful not to include duplicates if we loop back to ANSTO?
             # But standard VRP usually doesn't revisit unless it's depot.
             # step['name']
             original_h = next(h for h in self.hospitals if h.name == step['name'])
             remaining_hospitals.append(original_h)
             
        # 2. Generate Custom Matrix with Spike
        # We need to regenerate the matrix for this new subset of locations.
        # AND apply the penalty to the link roughly corresponding to "Current -> Immediate Dest"
        # Since "Current" is on the path to "Immediate Dest", the distance is short, 
        # BUT the "Disruption" implies the road ahead is blocked.
        # So we penalize "Current -> Immediate Dest" heavily.
        
        logger.info("Regenerating Distance Matrix for Reroute...")
        loc_dicts = [{"lat": h.lat, "lon": h.lon, "tier": h.tier} for h in remaining_hospitals]
        
        # Generate clean matrix first
        new_matrix = generate_distance_matrix(loc_dicts, None)
        
        # Apply Spike
        # Index 0 is Current Loc. Index 1 correspond to remaining_steps[0] (Immediate Dest).
        # Spike (0 -> 1)
        original_time = new_matrix[0][1]
        new_matrix[0][1] *= 4.0 # 400%
        logger.info(f"Travel time {current_loc.name} -> {remaining_hospitals[1].name} spiked from {original_time:.1f} to {new_matrix[0][1]:.1f} min.")
        
        # 3. Solve Reroute
        logger.info("Optimizer: Re-calculating path...")
        reroute_optimizer = IsotopeOptimizer(hospitals_list=remaining_hospitals, custom_matrix=new_matrix)
        # Force 1 vehicle for this reroute (it's a single van recovery)
        reroute_optimizer.num_vehicles = 1 
        reroute_optimizer.vehicle_capacity = 10 # Assume enough capacity
        
        # Capture solution
        reroute_optimizer.solve_and_report()
        
        # 4. Compare
        # Original Plan for this segment:
        # Sum of durations of remaining steps?
        # The original plan was simple: Current -> Next -> ...
        # But we must account that the "Next" link is now 4x slower in REALITY.
        # So "Projected Delay" on Original Path = (Spiked Time - Original Time).
        
        projected_delay = new_matrix[0][1] - original_time
        logger.info(f"Projected Delay on Original Path: {projected_delay:.1f} min")
        
        # Check if Reroute found a better way?
        # The reroute result is in stdout/routes.json (overwritten).
        # We should probably parse it or capture it.
        # But for the report, we can just infer if the route CHANGED.
        # Did it skip node 1? Or go to node 2 first?
        # If node 1 is the ONLY way to node 2 (e.g. sequence), it might just accept the delay.
        # But if there's a triangle (Current -> Node 2 -> Node 1), it might swap.
        
        self.generate_comparison_report(projected_delay, remaining_hospitals, new_matrix)

    def generate_comparison_report(self, projected_delay, remaining_hospitals, matrix):
        """Generates markdown report."""
        
        report = f"""# Dynamic Stress Test Report: Black Swan Event

## Disruption
*   **Event**: Major highway closure (400% traffic spike).
*   **Location**: En route to {remaining_hospitals[1].name}.
*   **Detection Time**: T=120 min.

## Impact Analysis
*   **Projected Delay (Original path)**: {projected_delay:.1f} minutes.
*   **Reroute Decision**: The optimizer recalculated the path based on the blocked link.

*(Check output/routes.json for the final executed reroute path)*

## Isotope Potency
*   **Mitigation**: Rerouting attempts to minimize the total delay. 
*   **Outcome**: If the delay was successfully avoided by visiting other nodes first (if geometrically possible) or if the delay was unavoidable but minimized.
"""
        with open("comparison_report.md", "w") as f:
            f.write(report)
        logger.info("Comparison Report generated: comparison_report.md")

if __name__ == "__main__":
    sim = TransportSimulator()
    sim.run_simulation()
