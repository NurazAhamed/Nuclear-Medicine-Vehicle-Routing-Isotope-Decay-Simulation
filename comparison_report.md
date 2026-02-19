# Dynamic Stress Test Report: Black Swan Event

## Disruption
*   **Event**: Major highway closure (400% traffic spike).
*   **Location**: En route to Gosford Hospital.
*   **Detection Time**: T=120 min.

## Impact Analysis
*   **Projected Delay (Original path)**: 102.2 minutes.
*   **Reroute Decision**: The optimizer recalculated the path based on the blocked link.

*(Check output/routes.json for the final executed reroute path)*

## Isotope Potency
*   **Mitigation**: Rerouting attempts to minimize the total delay. 
*   **Outcome**: If the delay was successfully avoided by visiting other nodes first (if geometrically possible) or if the delay was unavoidable but minimized.
