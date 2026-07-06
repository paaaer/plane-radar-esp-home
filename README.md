# ESPHome Plane Radar

An [ESPHome](https://esphome.io) port of a desktop ADS-B plane radar: an ESP32-C3 and a 1.28″ round GC9A01 display (240×240) showing live aircraft around your location on a sonar-style radar screen — with native Home Assistant and MQTT integration on top.

Inspired by [MatixYo/ESP32-Plane-Radar](https://github.com/MatixYo/ESP32-Plane-Radar), which is a standalone Arduino/PlatformIO firmware. This project is a functional re-implementation as a single ESPHome YAML file so it can live alongside your other ESPHome devices, be configured from Home Assistant, and publish aircraft data over MQTT.

<img width="802" height="659" alt="image" src="https://github.com/user-attachments/assets/1e441e4f-3efd-4fbe-b448-197bf3d1eefa" />

## What it does

Every 5 seconds the device queries the free [adsb.fi](https://adsb.fi) open data API for aircraft within the configured range of your home coordinates. Each aircraft is converted from latitude/longitude into a distance and compass bearing relative to your location, then plotted on the round display:

- Black background with dark green range rings and crosshairs
- N / S / E / W compass labels on the bezel
- Range label on the east spoke
- Aircraft shown as red filled triangles pointing along their heading
- White trajectory lines extending from each triangle, scaled by speed
- Three-line tag per aircraft: callsign (white), type code (light blue), altitude (yellow)

At the same time, the aircraft list is published to Home Assistant and MQTT (see below).

## Hardware

| Display (GC9A01) | ESP32-C3 Super Mini |
|---|---|
| VCC | 3V3 (**not 5V**) |
| GND | GND |
| RST | GPIO0 |
| CS  | GPIO1 |
| DC  | GPIO10 |
| SDA (MOSI) | GPIO3 |
| SCL (SCLK) | GPIO4 |

The BOOT button on GPIO9 is used as the physical control. Same wiring as the original project, so the [original 3D-printed case](https://github.com/MatixYo/ESP32-Plane-Radar) designs fit unchanged.

The display is driven by ESPHome's `mipi_spi` platform (the `ili9xxx` platform is deprecated for this display family and produced garbled output on this panel in testing).

## Features

### Radar display
Dark green rings, crosshairs, and compass labels on a black background, with aircraft rendered as red triangles and white speed vectors, redrawn every 5 seconds.

### Facing-direction rotation
If the device isn't physically pointed north, set the **Facing Direction** entity to the compass heading you're facing (read it off your phone's compass app, e.g. `240` if you're looking southwest). The firmware computes the screen rotation as `(360 − facing) mod 360` and rotates the whole compass rose and every aircraft position so the sky in front of you is at the top of the screen. Aircraft bearings themselves stay true — only the on-screen orientation changes.

### Settings — persisted, adjustable live
All of these survive reboots and can be changed from Home Assistant or the device's built-in web dashboard (`http://plane-radar.local`), no reflash needed:

| Entity | Purpose |
|---|---|
| Home Latitude / Home Longitude | Radar center point |
| Radar Range | Slider, any radius 5–100 km |
| Units | km or mi (range label) |
| Facing Direction | Display rotation, entered as your compass heading |
| Runway Overlay | On/Off — draws teal runway strips for nearby airports |
| Outer Radius | How far beyond the ring range to show fringe dots (100–200%, default 133%) |

### Runway overlay
Draws runway strips (medium blue) with ICAO labels (lighter blue) for nearby airports, projected onto the radar exactly like aircraft. The YAML ships with Stockholm Arlanda (ESSA) and Uppsala/Ärna (ESCM) pre-filled.

To generate runway data for your own location, run the included `build_airports.py` script:

```bash
# Uses default location (Uppsala) and 150 km radius
python3 build_airports.py

# Or specify your own coordinates and radius
python3 build_airports.py 59.8586 17.6389 200
```

The script downloads the public-domain [OurAirports](https://ourairports.com) airport and runway CSVs, filters to airports within range that have usable runway threshold coordinates, and outputs a ready-to-paste block to both `airports_block.txt` and the console. Copy-paste it over the clearly marked `REPLACEABLE BLOCK` section in `plane-radar.yaml` (everything between and including the `===` marker lines), then recompile.

Each airport in the block is two lines of C++ (an ICAO label + a flat list of runway endpoint coordinates), with runway identifiers as comments so you can see what you're getting. Remove any airports you don't want — the firmware auto-filters by your live range anyway, so extra airports just cost a few bytes of flash.

### Web interface
The device hosts a built-in web dashboard at **`http://plane-radar.local`** (or its IP address) where all settings can be viewed and adjusted without Home Assistant. The interface provides sliders for Radar Range, Outer Radius, and Facing Direction, text fields for Home Latitude and Home Longitude, and dropdowns for Units and Runway Overlay. Changes take effect immediately — no reflash needed. The Aircraft Count sensor is also shown live.

<img width="1769" height="667" alt="image" src="https://github.com/user-attachments/assets/716fb4d9-569e-4450-bacc-8c3b769ff110" />


### Aircraft display
Each in-range aircraft renders as a small red filled triangle pointing in its direction of travel, with a white trajectory line extending from the nose tip whose length scales with ground speed (~1 px per 20 knots). The tag label is placed to the side of the aircraft (toward the center of the display to avoid edge clipping) with three lines: callsign (white), aircraft type code (light blue, if known from the transponder), and altitude in feet (yellow). Aircraft without heading data show as plain red dots.

Aircraft beyond the ring range but within the **Outer Radius** percentage appear as small red dots clamped to the edge of the display — the same "fringe dot" behavior as the original firmware. The default 133% matches the original's ratio (ring-3 label sits at ¾ of the outer ring, so the outer ring represents 4/3 of the labeled range).

### BOOT button
- **Short press** — jump to the next range preset above the current slider value (5 → 10 → 15 → 25 → 50 → 100 → 5 km)
- **Long press (3–10 s)** — factory reset of the persisted settings above

(Unlike the original, Wi-Fi credentials are compiled in from `secrets.yaml`, so there is no runtime Wi-Fi reset — change networks by editing secrets and re-uploading.)

### Home Assistant
Native ESPHome API integration: all settings entities plus an **Aircraft Count** sensor.

### MQTT
On every poll the device publishes:

- The standard ESPHome entity topics under `wifi2mqtt/plane-radar/...`
- A full aircraft list as one JSON payload on `wifi2mqtt/plane-radar/aircraft`:

```json
{
  "count": 2,
  "aircraft": [
    {
      "callsign": "SAS123",
      "hex": "4ac9e5",
      "registration": "SE-ROX",
      "type": "A20N",
      "squawk": "2044",
      "lat": 59.91,
      "lon": 17.55,
      "distance_km": 8.4,
      "bearing_from_home_deg": 312.7,
      "heading_deg": 205.0,
      "altitude_ft": 12000,
      "ground_speed_kt": 340.5,
      "vertical_rate_fpm": -1200
    }
  ]
}
```

Fields an aircraft's transponder didn't send are omitted rather than sent as zero/null. Note that ADS-B carries no destination airport — `heading_deg` (the aircraft's current track) is the closest available "where it's going" information.

## Setup

1. Create a new device in the ESPHome dashboard and paste in `plane-radar.yaml`.
2. Make sure your ESPHome `secrets.yaml` contains:
   ```yaml
   wifi_ssid: "..."
   wifi_password: "..."
   mqtt_broker: "..."
   mqtt_port: 1883
   mqtt_user: "..."
   mqtt_password: "..."
   ```
3. Adjust the `default_lat` / `default_lon` substitutions at the top of the YAML (or just set them later from Home Assistant).
4. Replace the `api:` encryption key with your own device's key.
5. Flash, then set your exact location, range, and facing direction from Home Assistant or `http://plane-radar.local`.

## How it works (implementation notes)

- Aircraft data lives in parallel `globals` vectors of plain types, so everything fits in a single YAML file with no external header.
- Distance uses the haversine formula; bearing uses the standard initial-bearing formula; both are computed on-device from raw lat/lon in the API response.
- Polar-to-screen projection maps `(bearing, distance)` to display pixels, clamped to the outer ring, with the rotation offset applied at draw time only.
- The adsb.fi endpoint queried is `https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{nm}` (distance converted from km to nautical miles on-device) and the response is parsed with ESPHome's built-in JSON support.

## Differences from the original

| | Original ([MatixYo/ESP32-Plane-Radar](https://github.com/MatixYo/ESP32-Plane-Radar)) | This port |
|---|---|---|
| Framework | Arduino / PlatformIO / LovyanGFX | ESPHome (`esp-idf`) |
| Wi-Fi setup | WiFiManager captive portal | Compiled-in from `secrets.yaml` |
| Config UI | Custom web portal | Home Assistant + ESPHome web dashboard |
| Runway overlay | Yes (full OurAirports database) | Yes (`build_airports.py` generates a pasteable block from OurAirports) |
| Smooth embedded font | Yes (Noto Sans VLW) | Roboto via `gfonts://` |
| Home Assistant | — | Native API integration |
| MQTT aircraft feed | — | Full JSON list every poll |
| Display rotation | — | Facing-direction entity |

## Credits

- Original project, concept, and hardware design: [MatixYo/ESP32-Plane-Radar](https://github.com/MatixYo/ESP32-Plane-Radar) (MIT)
- Aircraft data: [adsb.fi](https://adsb.fi) community open data API — please be considerate with polling frequency
- Built with [ESPHome](https://esphome.io)
