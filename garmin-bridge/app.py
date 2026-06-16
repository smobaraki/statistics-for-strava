"""Garmin-to-Strava API bridge.

Exposes Strava-compatible JSON endpoints backed by Garmin Connect data.
The Flask app is stateless except for an in-process Garmin session cache.
"""

import os
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import wraps
from typing import Optional

from flask import Flask, jsonify, request, Response
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("garmin-bridge")

# ── Config ──────────────────────────────────────────────────────────────────
CONFIG_DIR = Path(os.environ.get("GARMIN_CONFIG_DIR", os.path.expanduser("~/.GarminDb")))
CONFIG_FILE = CONFIG_DIR / "GarminConnectConfig.json"
CACHE_TTL_SECONDS = int(os.environ.get("GARMIN_CACHE_TTL", "300"))
BIND_HOST = os.environ.get("GARMIN_BRIDGE_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("GARMIN_BRIDGE_PORT", "5000"))

app = Flask(__name__)


# ── Simple TTL cache ────────────────────────────────────────────────────────
class TTLCache:
    def __init__(self, ttl: int):
        self._store: dict[str, tuple[float, object]] = {}
        self._ttl = ttl

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: object):
        self._store[key] = (time.monotonic(), value)

    def clear(self):
        self._store.clear()


cache = TTLCache(CACHE_TTL_SECONDS)

# ── Persistent polyline cache (survives bridge restarts) ────────────────────
POLYLINE_CACHE_DIR = CONFIG_DIR / "polyline_cache"


def _get_polyline_from_cache(activity_id: int) -> Optional[str]:
    """Read cached polyline from disk."""
    cache_file = POLYLINE_CACHE_DIR / f"{activity_id}.pl"
    if cache_file.is_file():
        content = cache_file.read_text().strip()
        if content == "__NONE__":
            return None
        return content
    return None


def _set_polyline_to_cache(activity_id: int, polyline: Optional[str]):
    """Write polyline to disk cache."""
    POLYLINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = POLYLINE_CACHE_DIR / f"{activity_id}.pl"
    cache_file.write_text(polyline if polyline else "__NONE__")


def _get_gear_from_cache(activity_id: int) -> Optional[str]:
    """Read cached gear UUID from disk."""
    cache_file = POLYLINE_CACHE_DIR / f"gear_{activity_id}.txt"
    if cache_file.is_file():
        content = cache_file.read_text().strip()
        if content and content != "__NONE__":
            return content
    return None


def _set_gear_to_cache(activity_id: int, gear_uuid: Optional[str]):
    """Write gear UUID to disk cache."""
    POLYLINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = POLYLINE_CACHE_DIR / f"gear_{activity_id}.txt"
    cache_file.write_text(gear_uuid if gear_uuid else "__NONE__")

# ── Garmin Connect session (singleton, recreated on auth failure) ───────────
_garmin: Optional[Garmin] = None
_display_name: Optional[str] = None


def _load_config() -> dict:
    # SnapDeploy / env-var based config
    env_user = os.environ.get("GARMIN_USER")
    env_pass = os.environ.get("GARMIN_PASSWORD")
    if env_user and env_pass:
        return {"user": env_user, "password": env_pass}

    if CONFIG_FILE.is_file():
        with open(CONFIG_FILE) as f:
            return json.load(f)

    return {}


def _get_garmin() -> Garmin:
    global _garmin, _display_name
    if _garmin is not None:
        return _garmin

    config = _load_config()
    email = config.get("user")
    password = config.get("password")
    token_file = str(CONFIG_DIR / "garmin_token.json")

    # Try env-var token first (for SnapDeploy etc.)
    env_token = os.environ.get("GARMIN_SESSION_TOKEN")
    if env_token and not os.path.isfile(token_file):
        try:
            import base64
            with open(token_file, "w") as f:
                f.write(base64.b64decode(env_token).decode())
            logger.info("Wrote session token from GARMIN_SESSION_TOKEN env var")
        except Exception as e:
            logger.warning("Failed to decode GARMIN_SESSION_TOKEN: %s", e)

    # Try cached token file
    if os.path.isfile(token_file):
        try:
            garmin = Garmin()
            garmin.login(token_file)
            _garmin = garmin
            _display_name = garmin.display_name
            logger.info("Logged in via cached token (display_name=%s)", _display_name)
            return garmin
        except (GarminConnectAuthenticationError, GarminConnectConnectionError) as e:
            logger.warning("Cached token failed: %s – falling back to credentials", e)

    if not email or not password:
        raise RuntimeError(
            "Missing Garmin credentials. Set GARMIN_USER and GARMIN_PASSWORD env vars, "
            "or place GarminConnectConfig.json in " + str(CONFIG_DIR)
        )

    token_file = str(CONFIG_DIR / "garmin_token.json")

    # Try cached token first
    if os.path.isfile(token_file):
        try:
            garmin = Garmin()
            garmin.login(token_file)
            _garmin = garmin
            _display_name = garmin.display_name
            logger.info("Logged in via cached token (display_name=%s)", _display_name)
            return garmin
        except (GarminConnectAuthenticationError, GarminConnectConnectionError) as e:
            logger.warning("Cached token failed: %s – falling back to credentials", e)

    # Fall back to credentials (only works if MFA prompt is available)
    try:
        garmin = Garmin(email=email, password=password)
        garmin.login(token_file)
        _garmin = garmin
        _display_name = garmin.display_name
        logger.info("Logged in with credentials (display_name=%s)", _display_name)
        return garmin
    except (GarminConnectAuthenticationError, GarminConnectConnectionError):
        # If MFA is required in a non-interactive context, tell the user to run setup_auth.py
        raise RuntimeError(
            "Garmin login failed. If MFA is required, run setup_auth.py locally first:\n"
            "  python3 garmin-bridge/setup_auth.py\n"
            f"Then ensure {token_file} is present in the config directory."
        )


def _reraise_on_auth_failure(func):
    """Decorator that re-authenticates once on auth-related failures."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        global _garmin
        try:
            return func(*args, **kwargs)
        except (GarminConnectAuthenticationError, GarminConnectConnectionError):
            _garmin = None  # force re-auth next time
            return func(*args, **kwargs)

    return wrapper


# ── Sport type mapping: Garmin parentTypeId → Strava sport_type string ─────
GARMIN_TO_STRAVA_SPORT: dict[int, str] = {
    1: "Run",
    2: "Ride",
    3: "Hike",
    4: "Walk",
    5: "Swim",
    6: "Workout",
    7: "WeightTraining",
    8: "Yoga",
    9: "Elliptical",
    10: "StairStepper",
    11: "Rowing",
    12: "Crossfit",
    13: "InlineSkate",
    14: "Tennis",
    15: "Golf",
    16: "Pilates",
    17: "BackcountrySki",
    18: "AlpineSki",
    19: "NordicSki",
    20: "Snowboard",
    21: "Snowshoe",
    22: "IceSkate",
    23: "StandUpPaddling",
    24: "RockClimbing",
    25: "Kayaking",
    26: "Canoeing",
    27: "Soccer",
    28: "Basketball",
    29: "Volleyball",
    30: "Dance",
    31: "HIIT",
    32: "VirtualRide",
    33: "VirtualRun",
    34: "VirtualRow",
}


def _map_sport_type(activity_type) -> str:
    if isinstance(activity_type, dict):
        parent_id = activity_type.get("parentTypeId") or activity_type.get("typeId", 0)
    else:
        parent_id = activity_type
    return GARMIN_TO_STRAVA_SPORT.get(parent_id, "Workout")


# ── Data mappers: Garmin JSON → Strava JSON ────────────────────────────────

def _get_or_extract_polyline(garmin, garmin_id: int) -> Optional[str]:
    """Get encoded polyline for an activity, downloading GPX if needed."""
    cache_key = f"polyline_{garmin_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "__NONE__" else None

    try:
        gpx_data = garmin.download_activity(garmin_id, dl_fmt=garmin.ActivityDownloadFormat.GPX)
    except Exception as e:
        logger.warning("Failed to download GPX for polyline %s: %s", garmin_id, e)
        cache.set(cache_key, "__NONE__")
        return None

    points = _extract_points_from_gpx(gpx_data)
    if points and len(points) > 1:
        polyline = _encode_polyline(points)
        cache.set(cache_key, polyline)
        return polyline

    cache.set(cache_key, "__NONE__")
    return None


def _extract_points_from_gpx(gpx_data: bytes) -> list[tuple[float, float]]:
    """Extract simplified track points from GPX data."""
    try:
        import gpxpy
    except ImportError:
        return []

    try:
        gpx = gpxpy.parse(gpx_data)
    except Exception:
        return []

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                points.append((pt.latitude, pt.longitude))

    # Simplify: keep at most ~2000 points to reduce polyline size
    if len(points) > 2000:
        step = len(points) // 2000
        points = points[::step]

    return points


def _activity_to_strava(act: dict, include_segment_efforts: bool = True) -> dict:
    """Convert a single Garmin activity dict to Strava-compatible JSON."""
    start_ms = act.get("startTimeLocal")
    if start_ms:
        if isinstance(start_ms, (int, float)):
            dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(start_ms).replace("Z", "+00:00"))
        start_local = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        start_local = "1970-01-01T00:00:00Z"

    distance_m = act.get("distance", 0)  # Garmin returns meters directly
    if distance_m > 500_000:  # unlikely activity, might be in cm
        distance_m = distance_m / 100

    # Garmin returns speed in km/h, Strava expects m/s
    avg_speed_kmh = act.get("averageSpeed", 0) or 0
    max_speed_kmh = act.get("maxSpeed", 0) or 0
    avg_speed_ms = avg_speed_kmh / 3.6
    max_speed_ms = max_speed_kmh / 3.6

    duration_s = round(act.get("duration", 0))
    moving_duration_s = round(act.get("movingDuration", duration_s))
    elapsed_duration_s = round(act.get("elapsedDuration", duration_s))

    start_lat = act.get("startLatitude")
    start_lng = act.get("startLongitude")
    start_latlng = [round(start_lat, 6), round(start_lng, 6)] if start_lat is not None and start_lng is not None else None

    polyline = act.get("polyline")  # may have been injected by _get_or_extract_polyline
    if not polyline:
        geo_points = act.get("geoPolylineDTO", {}).get("points", []) if act.get("geoPolylineDTO") else []
        if geo_points:
            polyline = _encode_polyline([(p["lat"], p["lon"]) for p in geo_points])

    avg_cadence = act.get("averageRunningCadenceInStepsPerMinute") or act.get("averageBikingCadenceInRevPerMinute")

    result = {
        "id": act.get("activityId"),
        "name": act.get("activityName", "Activity"),
        "sport_type": _map_sport_type(act.get("activityType", {})),
        "start_date_local": start_local,
        "distance": round(distance_m, 1),
        "total_elevation_gain": round(act.get("elevationGain", 0) or 0),
        "average_speed": round(avg_speed_ms, 3),
        "max_speed": round(max_speed_ms, 3),
        "moving_time": moving_duration_s,
        "elapsed_time": elapsed_duration_s,
        "average_heartrate": round(act.get("averageHR", 0)) if act.get("averageHR") else None,
        "max_heartrate": round(act.get("maxHR", 0)) if act.get("maxHR") else None,
        "average_cadence": round(avg_cadence) if avg_cadence else None,
        "average_watts": round(act.get("averagePower", 0)) if act.get("averagePower") else None,
        "max_watts": round(act.get("maxPower", 0)) if act.get("maxPower") else None,
        "calories": round(act.get("calories", 0)),
        "kilojoules": round(act.get("activeKilocalories", 0) * 4.184) if act.get("activeKilocalories") else round(act.get("calories", 0) * 4.184),
        "device_name": act.get("deviceName"),
        "start_latlng": start_latlng,
        "map": {"summary_polyline": polyline},
        "gear_id": act.get("gearId"),
        "commute": False,
        "workout_type": None,
        "visibility": "everyone",
        "total_photo_count": 0,
        "description": act.get("description"),
        "external_id": str(act.get("activityId")),
    }

    if include_segment_efforts:
        result["segment_efforts"] = []

    return result


def _encode_polyline(points: list[tuple[float, float]]) -> str:
    """Encode a list of (lat, lng) tuples as a Google encoded polyline."""
    if not points:
        return ""
    result = []
    prev_lat, prev_lng = 0, 0
    for lat, lng in points:
        dlat = round((lat - prev_lat) * 1e5)
        dlng = round((lng - prev_lng) * 1e5)
        prev_lat, prev_lng = lat, lng
        for val in (dlat, dlng):
            val = ~(val << 1) if val < 0 else (val << 1)
            while val >= 0x20:
                result.append(chr((0x20 | (val & 0x1F)) + 63))
                val >>= 5
            result.append(chr(val + 63))
    return "".join(result)


def _decode_polyline(polyline: str) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline to [(lat, lng), ...]."""
    points = []
    lat, lng = 0, 0
    index = 0
    length = len(polyline)
    while index < length:
        for coord in (0, 1):
            shift, result = 0, 0
            while True:
                byte = ord(polyline[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if not (byte & 0x20):
                    break
            if result & 1:
                result = ~result >> 1
            else:
                result >>= 1
            if coord == 0:
                lat += result
            else:
                lng += result
        points.append((lat / 1e5, lng / 1e5))
    return points


# ── GPX stream parsing ─────────────────────────────────────────────────────
def _parse_gpx_streams(gpx_data: bytes) -> list[dict]:
    """Parse GPX data into Strava-compatible stream arrays."""
    try:
        import gpxpy
    except ImportError:
        return []

    try:
        gpx = gpxpy.parse(gpx_data)
    except Exception:
        return []

    streams = {
        "time": [],
        "distance": [],
        "latlng": [],
        "altitude": [],
        "heartrate": [],
        "cadence": [],
        "velocity_smooth": [],
    }

    prev_point = None
    prev_time = None
    cumulative_dist = 0.0

    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                if pt.time is None:
                    continue

                ts = pt.time.timestamp()
                if prev_time is not None:
                    time_delta = ts - prev_time
                    if time_delta <= 0:
                        time_delta = 1
                else:
                    time_delta = 0

                if prev_point:
                    dist_delta = _haversine_distance(
                        prev_point[0], prev_point[1], pt.latitude, pt.longitude
                    )
                else:
                    dist_delta = 0
                cumulative_dist += dist_delta

                speed = dist_delta / time_delta if time_delta > 0 else 0

                streams["time"].append(int(ts))
                streams["distance"].append(round(cumulative_dist, 1))
                streams["latlng"].append([pt.latitude, pt.longitude])
                if pt.elevation is not None:
                    streams["altitude"].append(round(pt.elevation, 1))

                hr = None
                for ext in pt.extensions:
                    for child in ext:
                        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if tag == "hr":
                            hr = int(child.text)
                            break
                if hr is not None:
                    streams["heartrate"].append(hr)

                if speed > 0:
                    streams["velocity_smooth"].append(round(speed, 3))

                prev_point = (pt.latitude, pt.longitude)
                prev_time = ts

    result = []
    for stream_type, data in streams.items():
        if data and any(type(v) is list for v in data):
            # latlng needs special handling - keep as list of [lat,lng]
            pass
        if data:
            result.append({"type": stream_type, "data": data})

    return result


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── API routes ──────────────────────────────────────────────────────────────

@app.route("/api/v3/athlete", methods=["GET"])
def get_athlete():
    garmin = _get_garmin()
    profile = cache.get("garmin_profile")
    if profile is None:
        profile = garmin.get_user_summary(datetime.now().strftime("%Y-%m-%d"))
        if not profile:
            profile = {}
        cache.set("garmin_profile", profile)

    user_profile = profile.get("userProfile", {})
    return jsonify({
        "id": profile.get("profileId") or profile.get("userProfileId", 1),
        "firstname": user_profile.get("firstName") or _display_name or "Athlete",
        "lastname": user_profile.get("lastName", ""),
        "sex": user_profile.get("gender", "M"),
        "city": "",
        "state": "",
        "country": "",
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
    })


@app.route("/api/v3/athlete/activities", methods=["GET"])
def get_activities():
    garmin = _get_garmin()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 200))

    try:
        start = (page - 1) * per_page
        raw = garmin.get_activities(start, per_page)
    except Exception as e:
        logger.error("Failed to fetch activities: %s", e)
        return jsonify([])

    if not raw:
        return jsonify([])

    activities = []
    for a in raw:
        activity = _activity_to_strava(a, include_segment_efforts=True)
        aid = a.get("activityId")
        if aid:
            # Inject cached polyline and gear if available
            cached_pl = _get_polyline_from_cache(aid)
            if cached_pl:
                activity["map"] = {"summary_polyline": cached_pl}
            cached_gear = _get_gear_from_cache(aid)
            if cached_gear:
                activity["gear_id"] = cached_gear
        activities.append(activity)

    return jsonify(activities)


@app.route("/api/v3/activities/<activity_id>", methods=["GET"])
def get_activity(activity_id):
    garmin = _get_garmin()
    cache_key = f"activity_{activity_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        garmin_id = int(activity_id)
    except ValueError:
        return jsonify({"error": "Invalid activity ID"}), 400

    try:
        details = garmin.get_activity(garmin_id)
    except Exception as e:
        logger.error("Failed to fetch activity %s: %s", activity_id, e)
        return jsonify({"error": str(e)}), 404

    # The detail endpoint may nest data inside summaryDTO etc.
    # Flatten into the same format as the summary listing.
    if "summaryDTO" in details:
        summary = details.pop("summaryDTO", {})
        details = {**details, **summary}
    if "activityTypeDTO" in details and not details.get("activityType"):
        details["activityType"] = details.pop("activityTypeDTO")
    if "metadataDTO" in details:
        meta = details.pop("metadataDTO")
        if "deviceApplicationInstallationId" in meta and not details.get("deviceId"):
            details["deviceId"] = meta.get("deviceApplicationInstallationId")

    # Check if we have a cached polyline from a prior stream download
    polyline = _get_polyline_from_cache(garmin_id)
    if polyline:
        details["polyline"] = polyline

    # Look up gear for this activity
    try:
        gear_list = garmin.get_activity_gear(garmin_id)
        if gear_list:
            ginfo = gear_list[0]
            gear_uuid = ginfo.get("uuid")
            if gear_uuid:
                details["gearId"] = gear_uuid
                # Cache gear details for the /gear endpoint and summary listing
                cache.set(f"gear_{gear_uuid}", ginfo)
                _set_gear_to_cache(garmin_id, gear_uuid)
        else:
            _set_gear_to_cache(garmin_id, None)
    except Exception:
        pass  # gear lookup is optional

    activity = _activity_to_strava(details, include_segment_efforts=True)
    cache.set(cache_key, activity)
    return jsonify(activity)


@app.route("/api/v3/activities/<activity_id>/streams", methods=["GET"])
def get_activity_streams(activity_id):
    """Fetch activity streams by downloading and parsing the GPX file."""
    garmin = _get_garmin()
    cache_key = f"streams_{activity_id}"

    keys_param = request.args.get("keys", "")
    requested_keys = set(keys_param.split(",")) if keys_param else set()

    cached = cache.get(cache_key)
    if cached is not None:
        if requested_keys:
            cached = [s for s in cached if s["type"] in requested_keys]
        return jsonify(cached)

    try:
        garmin_id = int(activity_id)
    except ValueError:
        return jsonify([])

    try:
        gpx_data = garmin.download_activity(
            garmin_id, dl_fmt=garmin.ActivityDownloadFormat.GPX
        )
    except Exception as e:
        logger.error("Failed to download activity %s GPX: %s", activity_id, e)
        return jsonify([])

    # Cache polyline from GPX data for the activity detail endpoint
    points = _extract_points_from_gpx(gpx_data)
    if points and len(points) > 1:
        _set_polyline_to_cache(garmin_id, _encode_polyline(points))
    else:
        _set_polyline_to_cache(garmin_id, None)

    streams = _parse_gpx_streams(gpx_data)

    # Normalize time stream: convert absolute timestamps to relative seconds
    for s in streams:
        if s["type"] == "time":
            times = s["data"]
            if times:
                base = times[0]
                s["data"] = [t - base for t in times]

    cache.set(cache_key, streams)

    if requested_keys:
        streams = [s for s in streams if s["type"] in requested_keys]

    return jsonify(streams)


@app.route("/api/v3/activities/<activity_id>/zones", methods=["GET"])
def get_activity_zones(activity_id):
    # Garmin doesn't expose per-activity zones via the public API.
    return jsonify([])


@app.route("/api/v3/activities/<activity_id>/photos", methods=["GET"])
def get_activity_photos(activity_id):
    # Garmin doesn't expose photos via the public API.
    return jsonify([])


@app.route("/api/v3/gear/<gear_id>", methods=["GET"])
def get_gear(gear_id):
    garmin = _get_garmin()
    cache_key = f"gear_{gear_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify({
            "id": gear_id,
            "name": cached.get("displayName") or cached.get("customMakeModel", "Gear"),
            "distance": cached.get("totalDistance", 0) or 0,
            "retired": cached.get("gearStatusName") == "retired",
        })

    # Try numeric gear ID (fallback)
    try:
        gear = garmin.get_gear(gear_id)
        result = {
            "id": gear_id,
            "name": gear.get("displayName") or gear.get("customMakeModel", "Gear"),
            "distance": gear.get("totalDistance", 0) or 0,
            "retired": gear.get("retired", False),
        }
        cache.set(cache_key, result)
        return jsonify(result)
    except Exception:
        pass

    # Gear not found in cache or API - return minimal stub
    return jsonify({
        "id": gear_id,
        "name": "Gear",
        "distance": 0,
        "retired": False,
    })


@app.route("/api/v3/segments/<segment_id>", methods=["GET"])
def get_segment(segment_id):
    # Garmin doesn't have Strava-style segments.
    return jsonify({"error": "Segments not available from Garmin"}), 404


@app.route("/api/v3/push_subscriptions", methods=["GET", "POST", "DELETE"])
def push_subscriptions():
    # Webhooks are not supported.
    return jsonify([])


@app.route("/health", methods=["GET"])
def health():
    try:
        _get_garmin()
        return jsonify({"status": "ok", "garmin": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503


@app.route("/oauth/token", methods=["POST"])
def oauth_token():
    """Fake OAuth token endpoint so the PHP client doesn't break."""
    return jsonify({
        "access_token": "garmin-bridge-internal",
        "refresh_token": "garmin-bridge-internal",
        "expires_at": int(time.time()) + 86400,
        "token_type": "Bearer",
    })


# ── Entrypoint ──────────────────────────────────────────────────────────────

def main():
    logger.info("Garmin bridge starting on %s:%d", BIND_HOST, BIND_PORT)
    app.run(host=BIND_HOST, port=BIND_PORT, debug=False)


if __name__ == "__main__":
    main()
