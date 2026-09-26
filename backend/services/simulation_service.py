import math
import time


def build_simulation_updates():
    """
    Generates telemetry for software-only demo nodes.

    IMPORTANT:
    These nodes are always labelled SIMULATED.
    They are never presented as real hardware.
    """

    now = time.time()

    movement = (
        math.sin(now / 30.0)
        * 0.004
    )

    movement_2 = (
        math.cos(now / 34.0)
        * 0.004
    )

    temperature_1 = round(
        30.0
        + math.sin(now / 35.0) * 2.0,
        1
    )

    temperature_2 = round(
        31.0
        + math.sin(now / 40.0) * 1.5,
        1
    )

    temperature_3 = round(
        29.5
        + math.cos(now / 45.0) * 2.0,
        1
    )

    return {
        "vehicles": {
            "VEH-SIM-002": {
                "lat": 28.7041 + movement,
                "lon": 77.1025 + movement_2,
                "last_seen": now,
            },

            "VEH-SIM-003": {
                "lat": 28.6812 - movement_2,
                "lon": 77.2217 + movement,
                "last_seen": now,
            }
        },

        "junctions": {
            "JNC-SIM-002": {
                "last_seen": now,
                "current_light": (
                    int(now / 8) % 3
                ),
                "gas_value": 480,
                "gas_status": "NORMAL",
                "temperature": temperature_1,
                "camera_status": "SIMULATED_STREAM",
            },

            "JNC-SIM-003": {
                "last_seen": now,
                "current_light": (
                    int(now / 10) % 3
                ),
                "gas_value": 710,
                "gas_status": "POOR",
                "temperature": temperature_2,
                "camera_status": "SIMULATED_STREAM",
            },

            "JNC-SIM-004": {
                "last_seen": now,
                "current_light": (
                    int(now / 12) % 3
                ),
                "gas_value": 430,
                "gas_status": "NORMAL",
                "temperature": temperature_3,
                "camera_status": "SIMULATED_STREAM",
            }
        }
    }