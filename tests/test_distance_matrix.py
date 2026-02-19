import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from distance_matrix import generate_distance_matrix, get_haversine_distance, calculate_duration_fallback, Location, TfNSWClient

class TestDistanceMatrix(unittest.TestCase):

    def setUp(self):
        self.locations = [
            {'name': 'Source', 'lat': -34.0, 'lon': 150.0, 'tier': 0},
            {'name': 'Dest1', 'lat': -34.1, 'lon': 150.1, 'tier': 1},
            {'name': 'Dest2', 'lat': -35.0, 'lon': 151.0, 'tier': 3}
        ]

    def test_haversine_distance(self):
        """Verify Haversine calculation."""
        # Known distance approx: 1 deg lat is ~111km.
        l1 = Location(-34.0, 150.0)
        l2 = Location(-35.0, 150.0)
        dist = get_haversine_distance(l1, l2)
        self.assertAlmostEqual(dist, 111.19, delta=1.0)

    def test_fallback_calculation_tier1(self):
        """Verify Tier 1 fallback logic."""
        dist = 100.0
        # Tier 1: (100 * 1.4) / 50 = 2.8 hours = 168 mins
        duration = calculate_duration_fallback(dist, 1)
        self.assertAlmostEqual(duration, 168.0, places=1)

    def test_fallback_calculation_tier3(self):
        """Verify Tier 3 fallback logic."""
        dist = 100.0
        # Tier 3: 100 / 80 = 1.25 hours = 75 mins
        duration = calculate_duration_fallback(dist, 3)
        self.assertAlmostEqual(duration, 75.0, places=1)

    def test_matrix_generation_fallback(self):
        """Verify matrix generation using fallback (no client)."""
        matrix = generate_distance_matrix(self.locations, client=None)
        self.assertEqual(matrix.shape, (3, 3))
        self.assertEqual(matrix[0][0], 0.0)
        self.assertGreater(matrix[0][1], 0.0)

    @patch('distance_matrix.requests.get')
    def test_api_integration_mock(self, mock_get):
        """Verify API client is called and rate limiting is applied (implicitly)."""
        # Mock 200 OK response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'journeys': [{}]}
        mock_get.return_value = mock_response

        client = TfNSWClient(token="TEST_TOKEN")
        
        # Only run for small subset to save time
        short_locs = self.locations[:2]
        matrix = generate_distance_matrix(short_locs, client=client)
        
        self.assertEqual(matrix.shape, (2, 2))
        # Ensure requests.get was called
        # 2x2 matrix, diagonal=0. 
        # (0,1) and (1,0) should be called.
        self.assertEqual(mock_get.call_count, 2)

    @patch('distance_matrix.requests.get')
    def test_api_401_fallback(self, mock_get):
        """Verify fallback to Haversine on API 401 error."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        client = TfNSWClient(token="INVALID_TOKEN")
        short_locs = self.locations[:2]
        
        matrix = generate_distance_matrix(short_locs, client=client)
        
        # Should still generate a matrix using fallback
        self.assertEqual(matrix.shape, (2, 2))
        self.assertGreater(matrix[0][1], 0.0)

if __name__ == '__main__':
    unittest.main()
