import json
import os
from dataclasses import dataclass
from typing import List

@dataclass
class Hospital:
    name: str
    lat: float
    lon: float
    tier: int
    type: str

    def get_priority_weight(self) -> float:
        """
        Returns the priority weight based on the hospital's tier.
        Tier 3 (Remote): 1.0 (Highest priority/Lowest penalty)
        Tier 2 (Regional): 2.0
        Tier 1 (Metro): 3.0
        Tier 0 (Source): 0.0 (Excluded from delivery priority)
        """
        if self.tier == 3:
            return 1.0
        elif self.tier == 2:
            return 2.0
        elif self.tier == 1:
            return 3.0
        elif self.tier == 0:
            return 0.0 # Source
        else:
            raise ValueError(f"Invalid tier: {self.tier}")

def load_hospitals(file_path: str = "hospitals.json") -> List[Hospital]:
    """
    Loads hospitals from a JSON file.

    Args:
        file_path (str): The path to the JSON file. Defaults to "hospitals.json".

    Returns:
        List[Hospital]: A list of Hospital objects.
        
    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    # Robust path handling
    if not os.path.exists(file_path):
        # Try checking root if we are in a subdir
        root_path = os.path.join(os.getcwd(), "hospitals.json")
        if os.path.exists(root_path):
            file_path = root_path
        else:
             # Try checking relative to THIS file
             rel_path = os.path.join(os.path.dirname(__file__), '../../hospitals.json')
             if os.path.exists(rel_path):
                 file_path = rel_path
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find hospital data file at {file_path}")

    hospitals = []
    for entry in data:
        # Validate required fields could go here
        hospitals.append(Hospital(
            name=entry["name"],
            lat=entry["lat"],
            lon=entry["lon"],
            tier=entry["tier"],
            type=entry["type"]
        ))
    
    return hospitals
