import unittest
import os
import sys

# Add src to the system path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from data_loader import load_hospitals, Hospital

class TestDataLoader(unittest.TestCase):

    def setUp(self):
        # Path to the actual hospitals.json (assuming running from project root)
        self.file_path = "hospitals.json"
        if not os.path.exists(self.file_path):
             # Fallback if running from tests directory
             self.file_path = "../hospitals.json"

    def test_load_hospitals_count(self):
        """Verify that all 21 locations (ANSTO + 20 hospitals) are loaded."""
        hospitals = load_hospitals(self.file_path)
        self.assertEqual(len(hospitals), 21, "Should load exactly 21 locations")

    def test_ansto_loading(self):
        """Verify ANSTO (Source) is loaded correctly."""
        hospitals = load_hospitals(self.file_path)
        ansto = next((h for h in hospitals if h.name == "ANSTO Lucas Heights"), None)
        self.assertIsNotNone(ansto)
        self.assertEqual(ansto.tier, 0)
        self.assertEqual(ansto.type, "Source")

    def test_priority_weights(self):
        """Verify priority weights for different tiers."""
        # Mock hospitals for weight testing
        h3 = Hospital(name="T3", lat=0, lon=0, tier=3, type="Remote")
        h2 = Hospital(name="T2", lat=0, lon=0, tier=2, type="Regional")
        h1 = Hospital(name="T1", lat=0, lon=0, tier=1, type="Metro")
        
        self.assertEqual(h3.get_priority_weight(), 1.0)
        self.assertEqual(h2.get_priority_weight(), 2.0)
        self.assertEqual(h1.get_priority_weight(), 3.0)

    def test_wagga_correction(self):
        """Verify the data hygiene fix for Wagga Wagga (Tier 3)."""
        hospitals = load_hospitals(self.file_path)
        wagga = next((h for h in hospitals if h.name == "Wagga Wagga Hospital"), None)
        self.assertIsNotNone(wagga)
        self.assertEqual(wagga.tier, 3)
        self.assertEqual(wagga.lat, -35.1205)
        self.assertEqual(wagga.lon, 147.3601)

if __name__ == '__main__':
    unittest.main()
