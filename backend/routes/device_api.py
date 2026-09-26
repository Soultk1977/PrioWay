from flask import (
    Blueprint,
    jsonify,
    request,
)

from services.device_service import (
    device_service,
)

from services.verification_service import (
    verification_service,
)

from services.state_manager import (
    state_manager,
)


device_api = Blueprint(
    "device_api",
    __name__,
    url_prefix="/api/v1/device",
)


def authenticate_payload(
    payload,
):

    device_id = str(
        payload.get(
            "device_id",
            ""
        )
    ).strip()

    key = request.headers.get(
        "X-PrioWay-Device-Key",
        "",
    )

    ok, reason = (
        device_service.authenticate(
            device_id,
            key,
        )
    )

    return (
        ok,
        reason,
        device_id,
    )


# =========================================================
# DEVICE API HEALTH
# =========================================================

@device_api.get("/ping")
def ping():

    return jsonify({
        "success": True,
        "service":
            "PrioWay Device API",
        "status":
            "online",
    })


# =========================================================
# HEARTBEAT
# =========================================================

@device_api.post("/heartbeat")
def heartbeat():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ok, reason, device_id = (
        authenticate_payload(
            payload
        )
    )

    if not ok:

        return jsonify({
            "success": False,
            "error": reason,
        }), 401

    result = (
        device_service.heartbeat(
            device_id
        )
    )

    return jsonify(result)


# =========================================================
# VEHICLE GPS
# =========================================================

@device_api.post(
    "/vehicle/location"
)
def vehicle_location():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ok, reason, device_id = (
        authenticate_payload(
            payload
        )
    )

    if not ok:

        return jsonify({
            "success": False,
            "error": reason,
        }), 401

    if not device_id.startswith(
        "VEH-"
    ):

        return jsonify({
            "success": False,
            "error":
                "Not a vehicle device",
        }), 403

    result = (
        device_service
        .update_vehicle_location(
            device_id,
            payload.get("lat"),
            payload.get("lon"),
        )
    )

    return jsonify(result)


# =========================================================
# INTERNET EMERGENCY REQUEST
# =========================================================

@device_api.post(
    "/vehicle/emergency"
)
def vehicle_emergency():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ok, reason, device_id = (
        authenticate_payload(
            payload
        )
    )

    if not ok:

        return jsonify({
            "success": False,
            "error": reason,
        }), 401

    if not device_id.startswith(
        "VEH-"
    ):

        return jsonify({
            "success": False,
            "error":
                "Not a vehicle device",
        }), 403

    payload["vehicle_id"] = (
        device_id
    )

    payload.setdefault(
        "junction_id",
        "JNC-001",
    )

    result, code = (
        verification_service
        .submit_emergency(
            payload,
            source="DEVICE_INTERNET",
        )
    )

    # Bridge new Internet request into the
    # existing physical hardware state machine.
    if (
        device_id == "VEH-001"
        and
        result.get("result")
        in {
            "NEW_REQUEST",
            "DUPLICATE_REQUEST",
        }
    ):

        try:
            state_manager.emergency_request(
                "VEH-001",
                payload.get(
                    "junction_id",
                    "JNC-001",
                ),
            )
        except Exception:
            pass

    return jsonify(
        result
    ), code


# =========================================================
# JUNCTION TELEMETRY
# =========================================================

@device_api.post(
    "/junction/telemetry"
)
def junction_telemetry():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ok, reason, device_id = (
        authenticate_payload(
            payload
        )
    )

    if not ok:

        return jsonify({
            "success": False,
            "error": reason,
        }), 401

    if not device_id.startswith(
        "JNC-"
    ):

        return jsonify({
            "success": False,
            "error":
                "Not a junction device",
        }), 403

    result = (
        device_service
        .update_junction_telemetry(
            device_id,
            payload,
        )
    )

    return jsonify(result)


# =========================================================
# OLD UART EVENT THROUGH NEW AUTHENTICATED API
# =========================================================

@device_api.post(
    "/junction/event"
)
def junction_event():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ok, reason, device_id = (
        authenticate_payload(
            payload
        )
    )

    if not ok:

        return jsonify({
            "success": False,
            "error": reason,
        }), 401

    message = str(
        payload.get(
            "message",
            ""
        )
    ).strip()

    if not message:

        return jsonify({
            "success": False,
            "message":
                "message required",
        }), 400

    device_service.heartbeat(
        device_id
    )

    try:
        state_manager.junction_event(
            message
        )
    except Exception:
        pass

    return jsonify({
        "success": True,
        "device_id": device_id,
        "message_received": message,
    })
