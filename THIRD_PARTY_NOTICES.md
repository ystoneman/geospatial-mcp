# Third-party notices

This project stands on a lot of other people's work. This file records what it
depends on, under what terms, and what obligations that places on anyone
redistributing it.

No third-party source code is vendored into this repository. Everything below
is a dependency resolved at install time.

Licences were read from each package's own `LICENSE` file rather than from its
Python classifiers, because the two sometimes disagree — `numpy`, for one,
declares a plain `BSD-3-Clause` classifier but ships an SPDX expression covering
five licences. Where they conflict, the licence file governs and is what is
recorded here.

## Runtime dependencies

| Package | Licence | Notes |
|---|---|---|
| `mcp` | MIT | Model Context Protocol SDK |
| `pydantic` | MIT | |
| `httpx2` | BSD-3-Clause | via `mcp` |
| `numpy` | BSD-3-Clause, with 0BSD, MIT, Zlib and CC0-1.0 components | Declared as an SPDX expression |
| `shapely` | BSD-3-Clause | **bundles GEOS — see below** |
| `pyproj` | MIT | **bundles PROJ — see below** |
| `pygeodesy` | MIT | pure Python; rhumb lines and USNG/MGRS grid references |
| `h3` | Apache-2.0 | Uber H3 |
| `geohashr` | BSD-3-Clause | |
| `pluscodes` | Apache-2.0 | Open Location Code |
| `mercantile` | BSD-3-Clause | |
| `astral` | Apache-2.0 | |
| `tzfpy` | MIT | bundles tzf timezone boundary data |
| `geojson-pydantic` | MIT | |
| `polyline` | MIT | |
| `pyshp` | MIT | |

### Optional extras

| Extra | Packages | Licences |
|---|---|---|
| `terrain` | `pillow` | MIT-CMU |
| `orbit` | `sgp4`, `skyfield` | MIT, MIT |
| `stats` | `scikit-learn`, `esda`, `libpysal` | BSD-3-Clause |
| `optimize` | `fast-tsp` | MIT |
| `render` | `staticmap`, `pillow` | Apache-2.0, MIT-CMU |
| `raster` | `rasterio`, `rio-tiler`, `pystac-client`, `morecantile` | BSD-3, BSD-3, Apache-2.0, MIT |

Development-only dependencies (`pytest`, `ruff`, `mypy`, `hypothesis`) are not
distributed with the package. Note `hypothesis` is MPL-2.0; because it is
dev-only it never forms part of the distributed artefact.

## Bundled native libraries

### GEOS — LGPL-2.1-or-later

`shapely` wheels bundle a compiled copy of [GEOS](https://libgeos.org), which is
licensed under the **GNU Lesser General Public License, version 2.1 or later**.
This is the one copyleft component in the dependency tree, and it is
unavoidable: GEOS sits underneath Shapely, GeoPandas, OGR, PostGIS and
DuckDB-spatial alike, and there is no permissively-licensed replacement with
equivalent overlay and buffer correctness.

We satisfy LGPL-2.1 §6 as follows: GEOS is used unmodified; it is dynamically
linked rather than statically incorporated; this notice states that it is
LGPL-2.1 and where to obtain it; and nothing in our distribution prevents a
recipient from relinking against a different GEOS build. Source is available at
<https://libgeos.org/usage/download/>.

### PROJ — MIT

`pyproj` wheels bundle [PROJ](https://proj.org) (MIT) and its default
`proj.db`. Note that the high-accuracy datum-shift grids (NTv2, NADCON, geoid
models) are **not** included in the wheel. When a transform needs one and it is
absent, PROJ silently falls back to a less accurate operation — for British
National Grid, a 2 m Helmert shift instead of the 1 m OSTN15 grid.
`coord_transform_crs` names the operation it used, its accuracy, and the grid
file a better one would need. Set `PROJ_NETWORK=ON` to let PROJ fetch grids from
cdn.proj.org on demand; if that fetch fails, the tool falls back to the best
local operation and says so rather than returning PROJ's infinities.

## Data sources

The server queries public APIs at runtime. Their data carries its own terms,
independent of this software's licence. Each response includes the required
attribution in `meta.attribution`.

| Source | Data | Licence and obligations |
|---|---|---|
| [OpenStreetMap](https://www.openstreetmap.org/copyright) via Nominatim, Photon, Overpass and Valhalla | Geocoding, places, routing | **ODbL 1.0.** Attribution required on public display. Redistributing a derived database triggers share-alike. |
| [Open-Meteo](https://open-meteo.com) | Weather, elevation, air quality | **CC-BY 4.0.** The free tier is **non-commercial**; commercial use requires an API key or self-hosting. |
| Copernicus GLO-90 DEM (via Open-Meteo) | Elevation | © DLR e.V. 2010–2014, © Airbus Defence and Space GmbH 2014–2018 |
| [OpenCelliD](https://opencellid.org) (optional) | Cell towers | **CC-BY-SA 4.0.** Share-alike applies to derived databases. |
| [BeaconDB](https://beacondb.net) | Cell towers (keyless fallback) | Public domain (CC0) |
| [USGS](https://www.usgs.gov) | Earthquakes, elevation | Public domain |
| [NOAA / NWS](https://www.weather.gov) | Forecasts | Public domain |
| [CelesTrak](https://celestrak.org) | Orbital elements | Free to use with attribution |

## Adding a dependency

Record it here in the same commit. `scripts/check_attribution.sh` fails CI if a
source file carries an "Adapted from" header with no corresponding entry.

Do not introduce: `pycraf`, `pysolar`, `richdem`, `pysheds`, `pyroutelib3`,
`pyorbital` (GPL-3); `geohash`, `geohash2`, `pandana` (AGPL-3); `python-igraph`
(GPL-2, which transitively rules out `scikit-mobility` and `mappymatch`); or
`elkai` (proprietary, non-commercial only).
