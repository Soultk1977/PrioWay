import os

from services.database_service import (
    database_service,
)

from services.prioway_store import (
    prioway_store,
)

from services.verification_service import (
    verification_service,
)


class DemoService:

    def enabled(self):

        return (
            os.getenv(
                "PRIOWAY_DEMO_MODE",
                "1"
            )
            == "1"
        )

    def _disabled(self):

        return {
            "success": False,
            "message":
                "Demo mode disabled",
        }, 403

    # =====================================================
    # SUMMARY
    # =====================================================

    def summary(self):

        if not self.enabled():
            return self._disabled()

        return {
            "success": True,
            "demo_mode": True,
            "real_vehicle":
                "VEH-001",
            "real_junction":
                "JNC-001",
            "simulated_vehicles": [
                "VEH-SIM-002",
                "VEH-SIM-003",
            ],
            "simulated_junctions": [
                "JNC-SIM-002",
                "JNC-SIM-003",
                "JNC-SIM-004",
            ],
        }, 200

    # =====================================================
    # FAIL / RECOVER NODE
    # =====================================================

    def set_junction_health(
        self,
        junction_id,
        status,
    ):

        if not self.enabled():
            return self._disabled()

        junction = (
            prioway_store
            .set_simulated_junction_health(
                junction_id,
                status,
            )
        )

        if junction is None:

            return {
                "success": False,
                "message":
                    "Invalid simulated junction",
            }, 400

        return {
            "success": True,
            "junction": junction,
        }, 200

    # =====================================================
    # VERIFIED REQUEST
    # =====================================================

    def verified_request(self):

        if not self.enabled():
            return self._disabled()

        return verification_service.submit_emergency(
            {
                "vehicle_id":
                    "VEH-SIM-002",

                "junction_id":
                    "JNC-SIM-002",

                "hospital_id":
                    "HOSP-002",

                "priority":
                    "HIGH",
            },
            source="DEMO",
        )

    # =====================================================
    # UNVERIFIED REQUEST
    # =====================================================

    def unverified_request(self):

        if not self.enabled():
            return self._disabled()

        return verification_service.submit_emergency(
            {
                "vehicle_id":
                    "VEH-SIM-003",

                "junction_id":
                    "JNC-SIM-003",

                "hospital_id":
                    "HOSP-001",

                "priority":
                    "HIGH",
            },
            source="DEMO",
        )

    # =====================================================
    # FAKE UNKNOWN VEHICLE
    # =====================================================

    def fake_request(self):

        if not self.enabled():
            return self._disabled()

        return verification_service.submit_emergency(
            {
                "vehicle_id":
                    "FAKE-VEHICLE-999",

                "junction_id":
                    "JNC-SIM-002",

                "priority":
                    "HIGH",
            },
            source="DEMO",
        )

    # =====================================================
    # DUPLICATE REQUEST
    # =====================================================

    def duplicate_request(self):

        if not self.enabled():
            return self._disabled()

        first, _ = (
            verification_service
            .submit_emergency(
                {
                    "vehicle_id":
                        "VEH-SIM-002",

                    "junction_id":
                        "JNC-SIM-002",

                    "priority":
                        "HIGH",
                },
                source="DEMO",
            )
        )

        second, code = (
            verification_service
            .submit_emergency(
                {
                    "vehicle_id":
                        "VEH-SIM-002",

                    "junction_id":
                        "JNC-SIM-002",

                    "priority":
                        "HIGH",
                },
                source="DEMO",
            )
        )

        return {
            "success": True,
            "first": first,
            "second": second,
        }, code

    # =====================================================
    # RESET DEMO DATA
    # =====================================================

    def reset_demo(self):

        if not self.enabled():
            return self._disabled()

        database_service.execute(
            """
            DELETE FROM emergency_requests
            WHERE source = 'DEMO'
            """
        )

        database_service.execute(
            """
            UPDATE vehicles
            SET
                blacklisted = 0,
                blacklist_reason = NULL
            WHERE source = 'SIMULATED'
            """
        )

        database_service.execute(
            """
            UPDATE junctions
            SET forced_health = NULL
            WHERE source = 'SIMULATED'
            """
        )

        return {
            "success": True,
            "message":
                "Demo state reset",
        }, 200


demo_service = DemoService()
