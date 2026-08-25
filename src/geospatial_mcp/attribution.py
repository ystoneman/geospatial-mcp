"""Attribution strings for every upstream data source.

These are a licence obligation, not a courtesy. OpenStreetMap-derived data
(Nominatim, Photon, Overpass, Valhalla, OpenRouteService) is ODbL 1.0 and
requires attribution on any public display of results. OpenCelliD is
CC-BY-SA 4.0, which additionally imposes share-alike on derived databases.
Open-Meteo is CC-BY 4.0 and its free tier is non-commercial.

Every tool response carries the attribution for the sources it actually used,
in ``ResponseMeta.attribution``.
"""

from __future__ import annotations

__all__ = ["SOURCES", "Source", "attribution_for"]

Source = str

#: Canonical attribution line per source key.
SOURCES: dict[Source, str] = {
    "nominatim": "Geocoding © OpenStreetMap contributors, ODbL 1.0 (Nominatim)",
    "photon": "Geocoding © OpenStreetMap contributors, ODbL 1.0 (Photon/Komoot)",
    "overpass": "Map data © OpenStreetMap contributors, ODbL 1.0 (Overpass API)",
    "valhalla": "Routing © OpenStreetMap contributors, ODbL 1.0 (Valhalla/FOSSGIS)",
    "osrm": "Routing © OpenStreetMap contributors, ODbL 1.0 (OSRM)",
    "openrouteservice": (
        "Routing © OpenStreetMap contributors, ODbL 1.0 (openrouteservice by HeiGIT)"
    ),
    "open-meteo": (
        "Weather data by Open-Meteo.com, CC-BY 4.0. The free tier is for non-commercial use."
    ),
    "open-meteo-elevation": (
        "Elevation from Copernicus GLO-90 DEM via Open-Meteo.com, CC-BY 4.0. "
        "© DLR e.V. 2010-2014, © Airbus Defence and Space GmbH 2014-2018"
    ),
    "opentopodata": "Elevation via OpenTopoData; dataset licences vary by dataset",
    "terrarium": (
        "Elevation tiles from AWS Terrain Tiles (Mapzen/Terrarium), "
        "sourced from SRTM, Copernicus and national datasets"
    ),
    "usgs-epqs": "Elevation from the USGS 3D Elevation Program (3DEP), public domain",
    "usgs-earthquake": "Earthquake data from the USGS Earthquake Hazards Program, public domain",
    "nws": "Forecast data from the US National Weather Service (api.weather.gov), public domain",
    "opencellid": (
        "Cell tower data © OpenCelliD contributors, CC-BY-SA 4.0. "
        "Share-alike applies to derived databases."
    ),
    "beacondb": "Cell tower data from BeaconDB, a public-domain (CC0) crowdsourced dataset",
    "celestrak": "Orbital elements courtesy of CelesTrak (celestrak.org)",
}


def attribution_for(*sources: Source) -> list[str]:
    """Return the attribution lines for the given source keys, de-duplicated.

    Unknown keys are ignored rather than raising: a missing attribution line is
    a documentation bug, not a reason to fail a user's query.
    """
    seen: dict[str, None] = {}
    for key in sources:
        line = SOURCES.get(key)
        if line is not None:
            seen[line] = None
    return list(seen)
