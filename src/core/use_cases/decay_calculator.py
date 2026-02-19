import math

class DecayCalculator:
    """
    Calculates the radioactive decay of an isotope over time.
    """

    @staticmethod
    def calculate_remaining_activity(initial_activity: float, time_elapsed_hours: float, half_life_hours: float = 6.0) -> float:
        """
        Calculates the remaining activity after a given time period.

        Formula: A_t = A_0 * e^(-lambda * t)
        Where lambda = ln(2) / half_life

        Args:
            initial_activity (float): The initial activity of the isotope.
            time_elapsed_hours (float): The time elapsed in hours.
            half_life_hours (float, optional): The half-life of the isotope in hours. Defaults to 6.0 (Tc-99m).

        Returns:
            float: The remaining activity.
        """
        if half_life_hours <= 0:
            raise ValueError("Half-life must be greater than 0.")
        
        if time_elapsed_hours < 0:
             raise ValueError("Time elapsed cannot be negative.")

        decay_constant = math.log(2) / half_life_hours
        remaining_activity = initial_activity * math.exp(-decay_constant * time_elapsed_hours)
        return remaining_activity
