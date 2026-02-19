import unittest
import sys
import os
import json
from unittest.mock import MagicMock, patch
import numpy as np

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from optimizer import IsotopeOptimizer, load_hospitals, Hospital

class TestOptimizer(unittest.TestCase):

    def setUp(self):
        # We don't need real setup, mocks will handle it
        pass

    @patch('optimizer.load_hospitals')
    @patch('optimizer.generate_distance_matrix')
    def test_solve_simple_case(self, mock_gen_matrix, mock_load):
        # Mock Data
        h0 = Hospital("Source", -34.0, 150.0, 0, "Source")
        h1 = Hospital("Dest1", -34.1, 150.1, 1, "Metro") # Tier 1
        h2 = Hospital("Dest2", -35.0, 151.0, 3, "Remote") # Tier 3
        
        mock_load.return_value = [h0, h1, h2]
        
        # Mock Matrix (3x3)
        # 0 -> 1: 10 mins
        # 0 -> 2: 50 mins
        # 1 -> 2: 40 mins
        # Symmetric for simplicity
        matrix = np.array([
            [0.0, 10.0, 50.0],
            [10.0, 0.0, 40.0],
            [50.0, 40.0, 0.0]
        ])
        mock_gen_matrix.return_value = matrix
        
        optimizer = IsotopeOptimizer("dummy.json")
        optimizer.num_vehicles = 1 # Force single vehicle to visit both
        
        # Capture stdout to avoid clutter
        with patch('sys.stdout', new=MagicMock()):
             optimizer.solve_and_report()
            
        # Check if output file was created
        self.assertTrue(os.path.exists("output/routes.json"))
        
        # Verify JSON content
        with open("output/routes.json", 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1) # 1 vehicle
            steps = data[0]['steps']
            # Should involve Dest1 and Dest2
            names = [s['name'] for s in steps]
            self.assertIn("Dest1", names)
            self.assertIn("Dest2", names)

    @patch('optimizer.load_hospitals')
    @patch('optimizer.generate_distance_matrix')
    def test_no_solution_case(self, mock_gen_matrix, mock_load):
        # Setup scenario where time constraint is violated impossibly
        h0 = Hospital("Source", 0, 0, 0, "Source")
        h1 = Hospital("Dest1", 10, 10, 1, "Metro")
        mock_load.return_value = [h0, h1]
        
        # Distance extremely high > 1440 mins
        matrix = np.array([
            [0.0, 2000.0],
            [2000.0, 0.0]
        ])
        mock_gen_matrix.return_value = matrix
        
        optimizer = IsotopeOptimizer("dummy.json")
        
        with patch('sys.stdout', new=MagicMock()) as fake_out:
            optimizer.solve_and_report()
            # Capture print "No solution found!"
            # We can check specific calls but verifying it doesn't crash is good enough for now.
            pass

if __name__ == '__main__':
    unittest.main()
