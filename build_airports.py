#!/usr/bin/env python3
"""
build_airports.py — Generate a small airports.h for the ESPHome Plane Radar.

Adapted from the original ESP32-Plane-Radar build script
(scripts/build_large_airports.py by MatixYo), which builds a *worldwide*
large-airport dataset. This version instead keeps only the airports within a
fixed radius of your home location, so the firmware carries just the handful
of airports you can actually see — not the whole planet.

The device still does the final, live filtering against your runtime range
slider; this script just trims the global list down to a sensible neighbourhood
at compile time. Set FILTER_RADIUS_KM comfortably above your maximum slider
range (default 150 km vs a 100 km max slider) so changing the slider never asks
for an airport that wasn't baked in.

Usage:
    python3 build_airports.py                 # uses HOME_LAT/HOME_LON below
    python3 build_airports.py 59.8586 17.6389 # or pass lat lon on the cmd line
    python3 build_airports.py 59.8586 17.6389 200   # ...and a custom radius km

Output:
    airports.h   (next to this script) — include it from plane-radar.yaml
"""

from __future__ import annotations

import csv
import io
import math
import sys
import urllib.request
import ssl
from pathlib import Path

# --- Defaults: your home location and how far out to keep airports ----------
HOME_LAT = 53.743      # Quickbornerheide
HOME_LON = 9.953
FILTER_RADIUS_KM = 150  # keep airports within this radius of home

# Which OurAirports "type" values to include. The original keeps only
# large_airport; medium_airport pulls in regional fields like Uppsala/Ärna,
# which is usually what you want for a local radar.
KEEP_TYPES = {"large_airport", "medium_airport"}

OUT_TXT = Path(__file__).resolve().parent / "airports_block.txt"

AIRPORTS_URL = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/"
    "airports.csv"
)
RUNWAYS_URL = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/"
    "runways.csv"
)


def fetch_csv(url: str) -> list[dict[str, str]]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    print(f"downloading {url.rsplit('/', 1)[-1]} ...")
    with urllib.request.urlopen(url, timeout=120, context= ctx) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fnum(s: str | None) -> float | None:
    if not s or not s.strip():
        return None
    try:
        return float(s)
    except ValueError:
        return None


def is_h_designator(s: str) -> bool:
    if not s or s[0] != "H":
        return False
    rest = s[1:]
    if not rest or rest[0] in "-_":
        return True
    return rest.isdigit()


def is_helipad(row: dict[str, str]) -> bool:
    le = (row.get("le_ident") or "").strip().upper()
    he = (row.get("he_ident") or "").strip().upper()
    if not is_h_designator(le) and not is_h_designator(he):
        return False
    try:
        length_ft = int(row.get("length_ft") or 0)
    except ValueError:
        length_ft = 0
    if is_h_designator(le) and is_h_designator(he):
        return True
    return length_ft < 2500


def build(home_lat: float, home_lon: float, radius_km: float):
    airports = fetch_csv(AIRPORTS_URL)
    runways = fetch_csv(RUNWAYS_URL)

    # 1. Airports of the right type, within radius of home.
    nearby: dict[str, dict] = {}
    for a in airports:
        if a.get("type") not in KEEP_TYPES:
            continue
        ident = (a.get("ident") or "").strip()
        if not ident:
            continue
        lat = fnum(a.get("latitude_deg"))
        lon = fnum(a.get("longitude_deg"))
        if lat is None or lon is None:
            continue
        if haversine_km(home_lat, home_lon, lat, lon) > radius_km:
            continue
        nearby[ident] = {"ident": ident, "runways": []}

    # 2. Attach runway segments (both thresholds present, not closed, not helipad).
    for r in runways:
        if r.get("closed") == "1":
            continue
        ap = (r.get("airport_ident") or "").strip()
        if ap not in nearby:
            continue
        if is_helipad(r):
            continue
        le_lat = fnum(r.get("le_latitude_deg"))
        le_lon = fnum(r.get("le_longitude_deg"))
        he_lat = fnum(r.get("he_latitude_deg"))
        he_lon = fnum(r.get("he_longitude_deg"))
        if None in (le_lat, le_lon, he_lat, he_lon):
            continue
        try:
            length_ft = int(r.get("length_ft") or 0)
        except ValueError:
            length_ft = 0
        nearby[ap]["runways"].append(
            {
                "le_lat": le_lat, "le_lon": le_lon,
                "he_lat": he_lat, "he_lon": he_lon,
                "length_ft": length_ft,
                "le_ident": (r.get("le_ident") or "").strip(),
                "he_ident": (r.get("he_ident") or "").strip(),
            }
        )

    # 3. Drop airports that ended up with no usable runway coordinates,
    #    sort runways longest-first, airports by distance from home.
    result = []
    for ap in nearby.values():
        if not ap["runways"]:
            continue
        ap["runways"].sort(key=lambda x: -x["length_ft"])
        result.append(ap)
    result.sort(
        key=lambda ap: haversine_km(
            home_lat, home_lon,
            ap["runways"][0]["le_lat"], ap["runways"][0]["le_lon"],
        )
    )
    return result


def render(airports: list[dict], home_lat: float, home_lon: float, radius_km: float) -> str:
    """Emit the pasteable block for the on_boot lambda in plane-radar.yaml.

    Copy-paste the full output over everything between (and including) the
    two === markers in the 'AIRPORT DATA — REPLACEABLE BLOCK' section.
    """
    lines = [
        "          // ================= AIRPORT DATA — REPLACEABLE BLOCK =================",
        "          // Each airport: one push_back to rw_icao (its ICAO label) and one",
        "          // matching push_back to rw_lines holding its runway endpoint coords,",
        "          // flattened as {lat1,lon1,lat2,lon2, ...} (4 numbers per runway).",
        "          //",
        "          // To regenerate for a different location, run build_airports.py and",
        "          // paste its output over everything between the two === markers.",
        "          // Coordinates are WGS84 decimal degrees.",
        "          // ===================================================================",
        f"          // Airports within {radius_km:.0f} km of"
        f" ({home_lat:.4f}, {home_lon:.4f}). Generated by build_airports.py.",
    ]
    for ap in airports:
        lines.append(f'          id(rw_icao).push_back("{ap["ident"]}");')
        lines.append("          id(rw_lines).push_back({")
        rws = ap["runways"]
        for i, rw in enumerate(rws):
            comma = "," if i < len(rws) - 1 else ""
            le = rw.get("le_ident", "")
            he = rw.get("he_ident", "")
            rwy_label = f"   // {le}/{he}" if le else ""
            lines.append(
                f'            {rw["le_lat"]:.6f}, {rw["le_lon"]:.6f}, '
                f'{rw["he_lat"]:.6f}, {rw["he_lon"]:.6f}{comma}{rwy_label}'
            )
        lines.append("          });")
        lines.append("")
    lines.append("          // =============== END AIRPORT DATA — REPLACEABLE BLOCK ==============")
    return "\n".join(lines)


def main() -> int:
    home_lat, home_lon, radius = HOME_LAT, HOME_LON, FILTER_RADIUS_KM
    if len(sys.argv) >= 3:
        home_lat = float(sys.argv[1])
        home_lon = float(sys.argv[2])
    if len(sys.argv) >= 4:
        radius = float(sys.argv[3])

    airports = build(home_lat, home_lon, radius)
    output = render(airports, home_lat, home_lon, radius)
    OUT_TXT.write_text(output, encoding="utf-8")

    total_rw = sum(len(a["runways"]) for a in airports)
    print(f"\n{'='*60}")
    print(f" Found {len(airports)} airports, {total_rw} runways")
    print(f" within {radius:.0f} km of ({home_lat:.4f}, {home_lon:.4f})")
    print(f"{'='*60}")
    for a in airports:
        rwy_names = ", ".join(
            f'{r["le_ident"]}/{r["he_ident"]}' for r in a["runways"]
        )
        print(f"  {a['ident']:5s}  {len(a['runways'])} runway(s): {rwy_names}")
    print(f"\nSaved to: {OUT_TXT.name}")
    print(
        "\nCopy-paste the contents of that file over the REPLACEABLE BLOCK\n"
        "in plane-radar.yaml (everything between and including the === lines).\n"
    )
    print("--- Pasteable block: ---\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
