"""One module per upstream provider.

Each module owns request construction, response parsing and provider-specific
error shapes for exactly one service, and returns plain Python structures. No
module here knows anything about MCP.

Every provider that requires an API key has a keyless default alternative, so
the server is fully useful with no signup:

===================  ==========================  ==========================
Capability           Keyless default             Optional keyed upgrade
===================  ==========================  ==========================
Geocoding            Nominatim / Photon          --
POI search           Overpass                    --
Routing              Valhalla (FOSSGIS)          OpenRouteService
Weather              Open-Meteo                  Open-Meteo commercial
Elevation            Open-Meteo / OpenTopoData   --
Cell towers          BeaconDB                    OpenCelliD
===================  ==========================  ==========================
"""
