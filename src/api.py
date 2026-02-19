from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel
import sys
import os
import json
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from src.core.optimizer import IsotopeOptimizer
from src.core.data_loader import load_hospitals
from src.core.simulator_dynamic import DynamicSimulator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

app = FastAPI(title="Medical Isotope Dispatch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AvoidPoint(BaseModel):
    lat: float
    lon: float

class OptimizeRequest(BaseModel):
    avoid_point: Optional[AvoidPoint] = None

@app.get("/hospitals")
def get_hospitals():
    """Returns geo-data for all 21 locations."""
    hospitals = load_hospitals("hospitals.json")
    return [
        {
            "name": h.name,
            "lat": h.lat,
            "lon": h.lon,
            "tier": h.tier,
            "type": h.type
        }
        for h in hospitals
    ]

@app.post("/optimize")
def optimize_routes(request: Optional[OptimizeRequest] = None):
    """Triggers solver. Returns { routes: [...], analytics: {...} }."""
    try:
        optimizer = IsotopeOptimizer()
        
        avoid_dict = None
        if request and request.avoid_point:
            avoid_dict = {"lat": request.avoid_point.lat, "lon": request.avoid_point.lon}
            
        optimizer.solve_and_report(avoid_point=avoid_dict)
        
        if os.path.exists("output/routes.json"):
            with open("output/routes.json", 'r') as f:
                data = json.load(f)
            return data
        else:
             raise HTTPException(status_code=500, detail="Optimization failed to produce output.")
    except Exception as e:
        logger.error(f"Optimization error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/simulate-disruption")
def simulate_disruption():
    """Triggers Phase 5 'Black Swan' logic."""
    try:
        sim = DynamicSimulator()
        sim.run_m5_scenario()
        
        rerouted_plan = []
        if os.path.exists("output/routes.json"):
            with open("output/routes.json", 'r') as f:
                rerouted_plan = json.load(f)
                
        summary = "Simulation complete."
        if os.path.exists("simulation_log.md"):
            with open("simulation_log.md", 'r') as f:
                summary = f.read()
                
        return {
            "rerouted_plan": rerouted_plan,
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Simulation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
