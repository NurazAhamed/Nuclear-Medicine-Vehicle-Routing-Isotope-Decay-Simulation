import unittest
import math
import sys
import os

# Add src to the system path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../src')))

from core.use_cases.decay_calculator import DecayCalculator

class TestDecayCalculator(unittest.TestCase):
    
    def test_half_life_decay(self):
        """Test that activity is exactly half after one half-life."""
        initial_activity = 100.0
        remaining = DecayCalculator.calculate_remaining_activity(initial_activity, 6.0, 6.0)
        self.assertAlmostEqual(remaining, 50.0, places=5)

    def test_two_half_lives(self):
        """Test that activity is exactly quarter after two half-lives."""
        initial_activity = 100.0
        remaining = DecayCalculator.calculate_remaining_activity(initial_activity, 12.0, 6.0)
        self.assertAlmostEqual(remaining, 25.0, places=5)

    def test_zero_time(self):
        """Test that activity is unchanged if no time has passed."""
        initial_activity = 100.0
        remaining = DecayCalculator.calculate_remaining_activity(initial_activity, 0.0, 6.0)
        self.assertEqual(remaining, 100.0)

    def test_zero_activity(self):
        """Test that zero initial activity results in zero remaining activity."""
        remaining = DecayCalculator.calculate_remaining_activity(0.0, 5.0, 6.0)
        self.assertEqual(remaining, 0.0)

    def test_custom_half_life(self):
        """Test decay with a different half-life (e.g., 1 hour)."""
        initial_activity = 100.0
        remaining = DecayCalculator.calculate_remaining_activity(initial_activity, 1.0, 1.0)
        self.assertAlmostEqual(remaining, 50.0, places=5)

    def test_negative_time_error(self):
        """Test that negative time raises a ValueError."""
        with self.assertRaises(ValueError):
            DecayCalculator.calculate_remaining_activity(100.0, -1.0, 6.0)

    def test_invalid_half_life_error(self):
        """Test that zero or negative half-life raises a ValueError."""
        with self.assertRaises(ValueError):
            DecayCalculator.calculate_remaining_activity(100.0, 5.0, 0.0)

if __name__ == '__main__':
    unittest.main()
