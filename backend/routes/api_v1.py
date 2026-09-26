from flask import (
    Blueprint,
    jsonify,
    request,
)

from services.state_manager import state_manager
from services.prioway_store import prioway_store
from services.simulation_service import build_simulation_updates
from services.routing_service import routing_service
from services.verification_service import verification_service
from services.evidence_service import evidence_service
from services.demo_service import demo_service


api_v1 = Blueprint(
    "api_v1",
    __name__,
    url_prefix="/api/v1",
)


def refresh_prioway_data():

    snapshot = state_manager.snapshot()

    prioway_store.sync_physical_state(
        snapshot
    )

    prioway_store.apply_simulation(
        build_simulation_updates()
    )

    # Mirror a physical LoRa emergency into
    # the new multi-request database.
    emergency = snapshot.get(
        "emergency"
    )

    if (
        emergency
        and
        snapshot.get("state")
        == "EMERGENCY_PENDING"
    ):

        try:
            prioway_store.create_request(
                vehicle_id=emergency.get(
                    "vehicle",
                    "VEH-001",
                ),
                junction_id=emergency.get(
                    "junction",
                    "JNC-001",
                ),
                priority="HIGH",
                source="PHYSICAL_LORA",
            )
        except Exception:
            pass

    return snapshot


# =========================================================
# HEALTH / STATUS
# =========================================================

@api_v1.get("/health")
def health():

    refresh_prioway_data()

    return jsonify({
        "success": True,
        "project": "PrioWay",
        "api_version": "v1",
        "status": "online",
        "storage": "sqlite",
        "routing": "available",
        "device_api": "available",
        "evidence": "available",
        "demo_mode":
            demo_service.enabled(),
    })


@api_v1.get("/status")
def status():

    snapshot = refresh_prioway_data()

    vehicles = (
        prioway_store
        .list_vehicles()
    )

    junctions = (
        prioway_store
        .list_junctions()
    )

    requests_list = (
        prioway_store
        .list_requests()
    )

    active = [
        item
        for item in requests_list
        if item["status"] in {
            "PENDING",
            "VERIFIED",
            "APPROVED",
            "ACTIVATING",
            "ACTIVE",
        }
    ]

    unhealthy = [
        item
        for item in junctions
        if item.get(
            "health",
            {}
        ).get(
            "status"
        ) in {
            "OFFLINE",
            "FAILED",
        }
    ]

    snapshot["prioway"] = {
        "project": "PrioWay",
        "api_version": "v1",
        "storage": "sqlite",
        "vehicles_total":
            len(vehicles),
        "junctions_total":
            len(junctions),
        "active_requests":
            len(active),
        "unhealthy_junctions":
            len(unhealthy),
    }

    return jsonify(snapshot)


# =========================================================
# VEHICLES
# =========================================================

@api_v1.get("/vehicles")
def vehicles():

    refresh_prioway_data()

    return jsonify({
        "success": True,
        "vehicles":
            prioway_store
            .list_vehicles(),
    })


@api_v1.get(
    "/vehicles/<vehicle_id>"
)
def vehicle_detail(
    vehicle_id,
):

    refresh_prioway_data()

    vehicle = (
        prioway_store
        .get_vehicle(vehicle_id)
    )

    if vehicle is None:

        return jsonify({
            "success": False,
            "message":
                "Vehicle not found",
        }), 404

    return jsonify({
        "success": True,
        "vehicle": vehicle,
    })


@api_v1.get(
    "/vehicles/<vehicle_id>/location"
)
def vehicle_location(
    vehicle_id,
):

    refresh_prioway_data()

    vehicle = (
        prioway_store
        .get_vehicle(vehicle_id)
    )

    if vehicle is None:

        return jsonify({
            "success": False,
            "message":
                "Vehicle not found",
        }), 404

    return jsonify({
        "success": True,
        "vehicle_id": vehicle_id,
        "online":
            vehicle["online"],
        "location":
            vehicle["location"],
        "last_seen":
            vehicle["last_seen"],
    })


@api_v1.post(
    "/vehicles/<vehicle_id>/blacklist"
)
def blacklist_vehicle(
    vehicle_id,
):

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    vehicle = (
        prioway_store
        .set_blacklist(
            vehicle_id,
            True,
            data.get(
                "reason",
                "Manual blacklist",
            ),
        )
    )

    if vehicle is None:

        return jsonify({
            "success": False,
            "message":
                "Vehicle not found",
        }), 404

    return jsonify({
        "success": True,
        "vehicle": vehicle,
    })


@api_v1.post(
    "/vehicles/<vehicle_id>/restore"
)
def restore_vehicle(
    vehicle_id,
):

    vehicle = (
        prioway_store
        .set_blacklist(
            vehicle_id,
            False,
        )
    )

    if vehicle is None:

        return jsonify({
            "success": False,
            "message":
                "Vehicle not found",
        }), 404

    return jsonify({
        "success": True,
        "vehicle": vehicle,
    })


# =========================================================
# JUNCTIONS
# =========================================================

@api_v1.get("/junctions")
def junctions():

    refresh_prioway_data()

    return jsonify({
        "success": True,
        "junctions":
            prioway_store
            .list_junctions(),
    })


@api_v1.get(
    "/junctions/<junction_id>"
)
def junction_detail(
    junction_id,
):

    refresh_prioway_data()

    junction = (
        prioway_store
        .get_junction(
            junction_id
        )
    )

    if junction is None:

        return jsonify({
            "success": False,
            "message":
                "Junction not found",
        }), 404

    return jsonify({
        "success": True,
        "junction": junction,
    })


@api_v1.post(
    "/simulation/junctions/"
    "<junction_id>/health"
)
def simulation_health(
    junction_id,
):

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    junction = (
        prioway_store
        .set_simulated_junction_health(
            junction_id,
            data.get(
                "status",
                "",
            ),
        )
    )

    if junction is None:

        return jsonify({
            "success": False,
            "message":
                "Invalid simulated junction or status",
        }), 400

    return jsonify({
        "success": True,
        "junction": junction,
    })


# =========================================================
# REQUESTS
# =========================================================

@api_v1.get("/requests")
def emergency_requests():

    return jsonify({
        "success": True,
        "requests":
            prioway_store
            .list_requests(),
    })


@api_v1.post("/requests")
def create_request():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    result, code = (
        verification_service
        .submit_emergency(
            payload,
            source="API",
        )
    )

    return jsonify(result), code


@api_v1.get(
    "/requests/<request_id>"
)
def request_detail(
    request_id,
):

    item = (
        prioway_store
        .get_request(request_id)
    )

    if item is None:

        return jsonify({
            "success": False,
            "message":
                "Request not found",
        }), 404

    return jsonify({
        "success": True,
        "request": item,
    })


@api_v1.post(
    "/requests/<request_id>/approve"
)
def approve_request(
    request_id,
):

    old_item = (
        prioway_store
        .get_request(request_id)
    )

    item = (
        prioway_store
        .approve_request(request_id)
    )

    if item is None:

        return jsonify({
            "success": False,
            "message":
                "Request not found",
        }), 404

    # Physical request → keep existing
    # hardware command path operational.
    if (
        old_item
        and
        old_item.get("vehicle_id")
        == "VEH-001"
    ):
        try:
            state_manager.approve()
        except Exception:
            pass

    return jsonify({
        "success": True,
        "request": item,
    })


@api_v1.post(
    "/requests/<request_id>/reject"
)
def reject_request(
    request_id,
):

    old_item = (
        prioway_store
        .get_request(request_id)
    )

    item = (
        prioway_store
        .reject_request(request_id)
    )

    if item is None:

        return jsonify({
            "success": False,
            "message":
                "Request not found",
        }), 404

    if (
        old_item
        and
        old_item.get("vehicle_id")
        == "VEH-001"
    ):
        try:
            state_manager.reject()
        except Exception:
            pass

    return jsonify({
        "success": True,
        "request": item,
    })


@api_v1.post(
    "/requests/<request_id>/resolve"
)
def resolve_request(
    request_id,
):

    old_item = (
        prioway_store
        .get_request(request_id)
    )

    item = (
        prioway_store
        .resolve_request(request_id)
    )

    if item is None:

        return jsonify({
            "success": False,
            "message":
                "Request not found",
        }), 404

    if (
        old_item
        and
        old_item.get("vehicle_id")
        == "VEH-001"
    ):
        try:
            state_manager.reset()
        except Exception:
            pass

    return jsonify({
        "success": True,
        "request": item,
    })


# =========================================================
# HOSPITALS
# =========================================================

@api_v1.get("/hospitals")
def hospitals():

    return jsonify({
        "success": True,
        "hospitals":
            prioway_store
            .list_hospitals(),
    })


@api_v1.get(
    "/hospitals/<hospital_id>/incoming"
)
def hospital_incoming(
    hospital_id,
):

    return jsonify({
        "success": True,
        "hospital_id":
            hospital_id,
        "requests":
            prioway_store
            .hospital_incoming(
                hospital_id
            ),
    })


# =========================================================
# EVENTS
# =========================================================

@api_v1.get("/events")
def events():

    try:
        limit = int(
            request.args.get(
                "limit",
                100,
            )
        )

    except ValueError:
        limit = 100

    limit = max(
        1,
        min(limit, 250),
    )

    return jsonify({
        "success": True,
        "events":
            prioway_store
            .list_events(limit),
    })


# =========================================================
# GEOCODING
# =========================================================

@api_v1.get("/geocode")
def geocode():

    result = (
        routing_service.geocode(
            request.args.get(
                "q",
                ""
            )
        )
    )

    return jsonify(result), (
        200
        if result["success"]
        else 502
    )


# =========================================================
# ROUTING + HEALTH REROUTING
# =========================================================

@api_v1.post("/route")
def route():

    refresh_prioway_data()

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    destination = data.get(
        "destination"
    )

    if not isinstance(
        destination,
        dict,
    ):

        return jsonify({
            "success": False,
            "message":
                "destination is required",
        }), 400

    try:

        destination_lat = float(
            destination["lat"]
        )

        destination_lon = float(
            destination["lon"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):

        return jsonify({
            "success": False,
            "message":
                "Valid destination lat/lon required",
        }), 400

    vehicle_id = data.get(
        "vehicle_id"
    )

    start = data.get(
        "start"
    )

    if vehicle_id:

        vehicle = (
            prioway_store
            .get_vehicle(vehicle_id)
        )

        if vehicle is None:

            return jsonify({
                "success": False,
                "message":
                    "Vehicle not found",
            }), 404

        location = vehicle.get(
            "location",
            {}
        )

        if not location.get(
            "valid"
        ):

            return jsonify({
                "success": False,
                "message":
                    "Vehicle has no valid location",
            }), 409

        start_lat = location["lat"]
        start_lon = location["lon"]

    elif isinstance(
        start,
        dict,
    ):

        try:

            start_lat = float(
                start["lat"]
            )

            start_lon = float(
                start["lon"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):

            return jsonify({
                "success": False,
                "message":
                    "Invalid start coordinates",
            }), 400

    else:

        return jsonify({
            "success": False,
            "message":
                "vehicle_id or start required",
        }), 400

    result = (
        routing_service
        .calculate_route(
            start_lat=start_lat,
            start_lon=start_lon,

            destination_lat=
                destination_lat,

            destination_lon=
                destination_lon,

            junctions=
                prioway_store
                .list_junctions(),

            health_aware=bool(
                data.get(
                    "health_aware",
                    True,
                )
            ),
        )
    )

    return jsonify(result), (
        200
        if result.get("success")
        else 502
    )


# =========================================================
# EVIDENCE / PHOTO / VIDEO
# =========================================================

@api_v1.get("/evidence")
def evidence_list():

    try:
        limit = int(
            request.args.get(
                "limit",
                100,
            )
        )
    except ValueError:
        limit = 100

    limit = max(
        1,
        min(limit, 250),
    )

    return jsonify({
        "success": True,
        "evidence":
            evidence_service
            .list_evidence(limit),
    })


@api_v1.post("/evidence")
def evidence_upload():

    uploaded_file = (
        request.files.get("photo")
        or
        request.files.get("file")
    )

    result, code = (
        evidence_service
        .save_upload(
            uploaded_file,

            request_id=
                request.form.get(
                    "request_id"
                ),

            vehicle_id=
                request.form.get(
                    "vehicle_id"
                ),

            junction_id=
                request.form.get(
                    "junction_id"
                ),

            evidence_type=
                request.form.get(
                    "type",
                    "PHOTO",
                ),

            description=
                request.form.get(
                    "description"
                ),

            source=
                request.form.get(
                    "source",
                    "APP",
                ),
        )
    )

    return jsonify(result), code


# =========================================================
# MOBILE NOTIFICATION DEVICE REGISTRATION
# =========================================================

@api_v1.post(
    "/devices/register"
)
def register_mobile_device():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    result, code = (
        evidence_service
        .register_app_device(
            user_id=data.get(
                "user_id"
            ),

            device_token=data.get(
                "device_token"
            ),

            platform=data.get(
                "platform",
                "android",
            ),
        )
    )

    return jsonify(result), code


# =========================================================
# DEMO CONTROLS
# =========================================================

@api_v1.get("/demo/summary")
def demo_summary():

    result, code = (
        demo_service.summary()
    )

    return jsonify(result), code


@api_v1.post("/demo/reset")
def demo_reset():

    result, code = (
        demo_service.reset_demo()
    )

    return jsonify(result), code


@api_v1.post(
    "/demo/junctions/"
    "<junction_id>/fail"
)
def demo_fail_junction(
    junction_id,
):

    result, code = (
        demo_service
        .set_junction_health(
            junction_id,
            "FAILED",
        )
    )

    return jsonify(result), code


@api_v1.post(
    "/demo/junctions/"
    "<junction_id>/recover"
)
def demo_recover_junction(
    junction_id,
):

    result, code = (
        demo_service
        .set_junction_health(
            junction_id,
            "AUTO",
        )
    )

    return jsonify(result), code


@api_v1.post(
    "/demo/request/verified"
)
def demo_verified_request():

    result, code = (
        demo_service
        .verified_request()
    )

    return jsonify(result), code


@api_v1.post(
    "/demo/request/unverified"
)
def demo_unverified_request():

    result, code = (
        demo_service
        .unverified_request()
    )

    return jsonify(result), code


@api_v1.post(
    "/demo/request/fake"
)
def demo_fake_request():

    result, code = (
        demo_service
        .fake_request()
    )

    return jsonify(result), code


@api_v1.post(
    "/demo/request/duplicate"
)
def demo_duplicate_request():

    result, code = (
        demo_service
        .duplicate_request()
    )

    return jsonify(result), code
