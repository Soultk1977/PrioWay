import os

from flask import (
    Flask,
    jsonify,
    render_template,
    request
)

from services.state_manager import (
    state_manager
)

from routes.api_v1 import api_v1
from routes.device_api import device_api

# =========================================================
# PATHS
# =========================================================

BACKEND_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_ROOT = os.path.dirname(
    BACKEND_DIR
)

TEMPLATE_DIR = os.path.join(
    PROJECT_ROOT,
    "frontend",
    "templates"
)

STATIC_DIR = os.path.join(
    PROJECT_ROOT,
    "frontend",
    "static"
)


# =========================================================
# APP
# =========================================================

app = Flask(

    __name__,

    template_folder=
        TEMPLATE_DIR,

    static_folder=
        STATIC_DIR,

    static_url_path=
        "/static"
)

app.register_blueprint(api_v1)
app.config["MAX_CONTENT_LENGTH"] = (
    20 * 1024 * 1024
)
# =========================================================
# RESPONSE HELPER
# =========================================================

def manager_response(
    result
):

    success = result.get(
        "success",
        True
    )

    return jsonify(
        result
    ), (
        200
        if success
        else 409
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.get("/")
def index():

    return render_template(
        "index.html"
    )


# =========================================================
# STATUS
# =========================================================

@app.get("/api/status")
def api_status():

    return jsonify(
        state_manager.snapshot()
    )


# =========================================================
# EVENTS
# =========================================================

@app.get("/api/events")
def api_events():

    return jsonify({

        "events":
            state_manager
            .get_recent_events()
    })


# =========================================================
# EMERGENCY
# =========================================================

@app.post("/api/emergency")
def api_emergency():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    vehicle_id = data.get(
        "vehicle_id",
        "VEH-001"
    )

    junction_id = data.get(
        "junction_id",
        "JNC-001"
    )

    result = (
        state_manager
        .emergency_request(
            vehicle_id,
            junction_id
        )
    )

    return manager_response(
        result
    )


# =========================================================
# APPROVE
# =========================================================

@app.post("/api/approve")
def api_approve():

    return manager_response(
        state_manager.approve()
    )


# =========================================================
# REJECT
# =========================================================

@app.post("/api/reject")
def api_reject():

    return manager_response(
        state_manager.reject()
    )


# =========================================================
# RESET
# =========================================================

@app.post("/api/reset")
def api_reset():

    return manager_response(
        state_manager.reset()
    )


# =========================================================
# PI COMMAND POLLING
# =========================================================

@app.get("/api/pi/commands")
def pi_commands():

    state_manager.mark_pi_seen()

    return jsonify({

        "commands":
            state_manager
            .get_commands()
    })


# =========================================================
# PI ACK
# =========================================================

@app.post("/api/pi/ack")
def pi_ack():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    command_id = data.get(
        "command_id"
    )

    if (
        command_id
        is None
    ):

        return jsonify({

            "success":
                False,

            "message":
                "command_id required."

        }), 400

    state_manager.acknowledge(
        command_id
    )

    return jsonify({
        "success": True
    })


# =========================================================
# JUNCTION EVENT
# =========================================================

@app.post("/api/pi/junction-event")
def junction_event():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    message = data.get(
        "message"
    )

    if not message:

        return jsonify({

            "success":
                False,

            "message":
                "message required."

        }), 400

    state_manager.junction_event(
        message
    )

    return jsonify({
        "success": True
    })


# =========================================================
# VEHICLE GPS
# =========================================================

@app.post("/api/pi/vehicle-location")
def vehicle_location():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:

        lat = float(
            data["lat"]
        )

        lon = float(
            data["lon"]
        )

    except (
        KeyError,
        TypeError,
        ValueError
    ):

        return jsonify({

            "success":
                False,

            "message":
                "Valid lat and lon required."

        }), 400

    state_manager.update_vehicle_location(
        lat,
        lon
    )

    return jsonify({
        "success": True
    })


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    print(
        "======================================"
    )

    print(
        " ResQSync Control Server"
    )

    print(
        " Dashboard: http://127.0.0.1:5000"
    )

    print(
        " Pi backend: http://192.168.137.1:5000"
    )

    print(
        "======================================"
    )

    app.run(

        host=
            "0.0.0.0",

        port=
            5000,

        debug=
            True,

        use_reloader=
            False
    )
