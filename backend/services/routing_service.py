import math

import requests


OSRM_URL = (
    "https://router.project-osrm.org"
)

NOMINATIM_URL = (
    "https://nominatim.openstreetmap.org"
)

REQUEST_TIMEOUT = 12

# If an OFFLINE/FAILED junction is this close
# to the route, PrioWay considers rerouting.
JUNCTION_ROUTE_RADIUS_METERS = 350

# Distance used to create a demo detour point
# around a failed junction.
DETOUR_OFFSET_DEGREES = 0.012


class RoutingService:

    # =====================================================
    # DISTANCE HELPER
    # =====================================================

    def haversine_meters(
        self,
        lat1,
        lon1,
        lat2,
        lon2,
    ):

        radius = 6371000.0

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)

        d_phi = math.radians(
            lat2 - lat1
        )

        d_lambda = math.radians(
            lon2 - lon1
        )

        value = (
            math.sin(d_phi / 2) ** 2
            +
            math.cos(phi1)
            *
            math.cos(phi2)
            *
            math.sin(d_lambda / 2) ** 2
        )

        return (
            2
            *
            radius
            *
            math.atan2(
                math.sqrt(value),
                math.sqrt(1 - value),
            )
        )

    # =====================================================
    # GEOCODING
    # =====================================================

    def geocode(
        self,
        query,
    ):

        query = str(
            query
        ).strip()

        if not query:

            return {
                "success": False,
                "error":
                    "Search query is empty",
            }

        try:

            response = requests.get(
                (
                    f"{NOMINATIM_URL}"
                    "/search"
                ),
                params={
                    "q": query,
                    "format": "json",
                    "limit": 5,
                    "countrycodes": "in",
                },
                headers={
                    "User-Agent":
                        "PrioWay-Student-Project/1.0"
                },
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            results = []

            for item in data:

                try:

                    results.append({
                        "name":
                            item.get(
                                "display_name"
                            ),

                        "lat":
                            float(
                                item["lat"]
                            ),

                        "lon":
                            float(
                                item["lon"]
                            ),
                    })

                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue

            return {
                "success": True,
                "results": results,
            }

        except Exception as error:

            return {
                "success": False,
                "error":
                    str(error),
                "results": [],
            }

    # =====================================================
    # OSRM ROUTE
    # =====================================================

    def _request_osrm_route(
        self,
        coordinates,
    ):

        coordinate_text = ";".join(
            (
                f"{lon},{lat}"
            )
            for lat, lon
            in coordinates
        )

        url = (
            f"{OSRM_URL}"
            "/route/v1/driving/"
            f"{coordinate_text}"
        )

        response = requests.get(
            url,
            params={
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        routes = data.get(
            "routes",
            []
        )

        if not routes:

            raise RuntimeError(
                "No road route found"
            )

        route = routes[0]

        geometry = (
            route.get(
                "geometry",
                {}
            )
            .get(
                "coordinates",
                []
            )
        )

        return {
            "distance_meters":
                float(
                    route.get(
                        "distance",
                        0
                    )
                ),

            "duration_seconds":
                float(
                    route.get(
                        "duration",
                        0
                    )
                ),

            "geometry": geometry,
        }

    # =====================================================
    # ROUTE / JUNCTION DISTANCE
    # =====================================================

    def _junction_distance_to_route(
        self,
        junction,
        geometry,
    ):

        junction_lat = (
            junction.get("lat")
        )

        junction_lon = (
            junction.get("lon")
        )

        if (
            junction_lat is None
            or
            junction_lon is None
            or
            not geometry
        ):

            return None

        minimum = None

        # OSRM GeoJSON coordinates are:
        # [longitude, latitude]

        for coordinate in geometry:

            if len(coordinate) < 2:
                continue

            route_lon = coordinate[0]
            route_lat = coordinate[1]

            distance = (
                self.haversine_meters(
                    junction_lat,
                    junction_lon,
                    route_lat,
                    route_lon,
                )
            )

            if (
                minimum is None
                or
                distance < minimum
            ):

                minimum = distance

        return minimum

    # =====================================================
    # FIND FAILED JUNCTIONS ON ROUTE
    # =====================================================

    def _problem_junctions(
        self,
        junctions,
        geometry,
    ):

        problems = []

        for junction in junctions:

            health = (
                junction.get(
                    "health",
                    {}
                )
            )

            status = health.get(
                "status"
            )

            if status not in {
                "OFFLINE",
                "FAILED",
            }:
                continue

            distance = (
                self
                ._junction_distance_to_route(
                    junction,
                    geometry,
                )
            )

            if distance is None:
                continue

            if (
                distance
                <=
                JUNCTION_ROUTE_RADIUS_METERS
            ):

                problems.append({
                    "junction_id":
                        junction.get(
                            "junction_id"
                        ),

                    "name":
                        junction.get(
                            "name"
                        ),

                    "health":
                        status,

                    "distance_to_route_meters":
                        round(
                            distance,
                            1
                        ),

                    "lat":
                        junction.get(
                            "lat"
                        ),

                    "lon":
                        junction.get(
                            "lon"
                        ),
                })

        return problems

    # =====================================================
    # DETOUR POINTS
    # =====================================================

    def _detour_candidates(
        self,
        junction,
    ):

        lat = junction["lat"]
        lon = junction["lon"]

        offset = (
            DETOUR_OFFSET_DEGREES
        )

        return [
            (
                lat + offset,
                lon,
            ),

            (
                lat - offset,
                lon,
            ),

            (
                lat,
                lon + offset,
            ),

            (
                lat,
                lon - offset,
            ),

            (
                lat + offset,
                lon + offset,
            ),

            (
                lat - offset,
                lon - offset,
            ),
        ]

    # =====================================================
    # TRY ALTERNATE ROUTE
    # =====================================================

    def _find_detour_route(
        self,
        start,
        destination,
        problem_junction,
        junctions,
    ):

        candidates = (
            self._detour_candidates(
                problem_junction
            )
        )

        valid_routes = []

        for waypoint in candidates:

            try:

                route = (
                    self
                    ._request_osrm_route(
                        [
                            start,
                            waypoint,
                            destination,
                        ]
                    )
                )

                problems = (
                    self
                    ._problem_junctions(
                        junctions,
                        route[
                            "geometry"
                        ],
                    )
                )

                # Reject routes that still pass
                # through the same failed node.

                still_blocked = any(
                    item[
                        "junction_id"
                    ]
                    ==
                    problem_junction[
                        "junction_id"
                    ]
                    for item in problems
                )

                if still_blocked:
                    continue

                valid_routes.append(
                    route
                )

            except Exception:
                continue

        if not valid_routes:

            return None

        return min(
            valid_routes,
            key=lambda item:
                item[
                    "distance_meters"
                ],
        )

    # =====================================================
    # ETA
    # =====================================================

    def _eta_data(
        self,
        route,
    ):

        distance_km = (
            route[
                "distance_meters"
            ]
            / 1000.0
        )

        standard_minutes = (
            route[
                "duration_seconds"
            ]
            / 60.0
        )

        # Current demonstration model:
        # green corridor average speed
        # assumed approximately 75 km/h.

        if distance_km > 0:

            green_minutes = (
                distance_km
                / 75.0
                * 60.0
            )

        else:

            green_minutes = 0

        time_saved = max(
            0,
            standard_minutes
            -
            green_minutes,
        )

        return {
            "distance_km":
                round(
                    distance_km,
                    2
                ),

            "eta_minutes":
                round(
                    standard_minutes,
                    1
                ),

            "green_corridor_eta_minutes":
                round(
                    green_minutes,
                    1
                ),

            "estimated_time_saved_minutes":
                round(
                    time_saved,
                    1
                ),

            "eta_note": (
                "OSRM road estimate; "
                "green corridor ETA is "
                "a demonstration model, "
                "not live traffic data."
            ),
        }

    # =====================================================
    # MAIN ROUTE FUNCTION
    # =====================================================

    def calculate_route(
        self,
        start_lat,
        start_lon,
        destination_lat,
        destination_lon,
        junctions,
        health_aware=True,
    ):

        start = (
            float(start_lat),
            float(start_lon),
        )

        destination = (
            float(destination_lat),
            float(destination_lon),
        )

        try:

            original_route = (
                self
                ._request_osrm_route(
                    [
                        start,
                        destination,
                    ]
                )
            )

        except Exception as error:

            return {
                "success": False,
                "error":
                    f"Routing failed: {error}",
            }

        original_problems = []

        if health_aware:

            original_problems = (
                self
                ._problem_junctions(
                    junctions,
                    original_route[
                        "geometry"
                    ],
                )
            )

        selected_route = (
            original_route
        )

        rerouted = False

        avoided_junctions = []

        # For this student/demo implementation,
        # reroute around the first failed junction
        # detected on the route.

        if original_problems:

            first_problem = (
                original_problems[0]
            )

            detour_route = (
                self
                ._find_detour_route(
                    start,
                    destination,
                    first_problem,
                    junctions,
                )
            )

            if detour_route:

                selected_route = (
                    detour_route
                )

                rerouted = True

                avoided_junctions.append(
                    first_problem[
                        "junction_id"
                    ]
                )

        eta = self._eta_data(
            selected_route
        )

        remaining_problems = (
            self
            ._problem_junctions(
                junctions,
                selected_route[
                    "geometry"
                ],
            )
            if health_aware
            else []
        )

        return {
            "success": True,

            "rerouted":
                rerouted,

            "health_aware":
                health_aware,

            "start": {
                "lat": start[0],
                "lon": start[1],
            },

            "destination": {
                "lat":
                    destination[0],

                "lon":
                    destination[1],
            },

            **eta,

            "route": {
                "type":
                    "LineString",

                "coordinates":
                    selected_route[
                        "geometry"
                    ],
            },

            "junction_health": {
                "problems_detected":
                    original_problems,

                "avoided_junctions":
                    avoided_junctions,

                "remaining_problems":
                    remaining_problems,
            },
        }


routing_service = RoutingService()