"""USNG / MGRS grid references.

One grid, two names. The Federal Geographic Data Committee adopted it as the
United States National Grid in 2001 (FGDC-STD-011-2001) for civilian use; the
same squares are called MGRS everywhere else, and the two are identical wherever
both are defined. USNG is a US-only standard, so a reference for Paris or Sydney
is properly called MGRS -- which is why the parameters and response fields here
say ``grid_reference`` rather than picking one of the two names.

It is the primary geo-referencing system the National Search and Rescue
Committee specifies for federal land SAR, and it is standard in wildland-fire
incident management and surveying. The properties that earn it that place are
engineering ones: purely alphanumeric with no minus signs or decimal points,
unambiguous over a voice radio, gracefully degrading in precision, and naming a
*square* rather than a point -- so a reported position carries its own implied
accuracy.

Conversion runs through pygeodesy rather than a binding to a national mapping
agency's C library: pure Python, no C extension, and already a dependency for
rhumb lines. Checked against NGA GEOTRANS over 3000 random global positions at
all five precisions -- 15000 comparisons, polar UPS zones included -- it differs
on one, by one metre in the last digit of a 1 m reference, where the two
transverse Mercator implementations disagree by under a millimetre.
"""

from __future__ import annotations

import re

from pygeodesy import toUtmUps8
from pygeodesy.mgrs import parseMGRS, toMgrs

from ..errors import GeoInputError

__all__ = [
    "PRECISION_METRES",
    "from_latlon",
    "is_grid_like",
    "normalize",
    "precision_of",
    "to_latlon",
]

#: Digits after the 100 km square letters -> the side of the square they name.
PRECISION_METRES: dict[int, int] = {0: 100_000, 2: 10_000, 4: 1_000, 6: 100, 8: 10, 10: 1}

#: Grid zone designator (1-2 digits + band letter), 100 km square (2 letters),
#: then an even number of digits. Polar UPS references have no zone number.
_GRID_RE = re.compile(r"^((?:\d{1,2}[C-HJ-NP-X]|[ABYZ])[A-HJ-NP-Z]{2})(\d{2,10})?$")

_EXAMPLE = "10S GJ 06832 44683  (or 10SGJ0683244683)"

#: Floating-point slack allowed when truncating to a grid square. See from_latlon.
#: The observed residue is 1 um; this is 100x that, and 100x below a millimetre.
_RESIDUE_M = 1e-5


def normalize(value: str) -> str:
    """Strip whitespace and upper-case a grid reference.

    Accepts every spacing convention in the wild: ``'10S GJ 06832 44683'``,
    ``'10SGJ0683244683'``, ``'10s gj 06832 44683'``.
    """
    return re.sub(r"\s+", "", value.strip().upper())


def is_grid_like(value: str) -> bool:
    """True if ``value`` is structurally a USNG/MGRS reference.

    Used by the polymorphic location parser to route input, so it must not
    raise and must not accept things that merely look numeric.
    """
    return bool(_GRID_RE.match(normalize(value)))


def precision_of(value: str) -> int:
    """Side length in metres of the square this reference names.

    A 100 km square (``'10SGJ'``) returns 100000; a full 10-digit reference
    returns 1.
    """
    match = _GRID_RE.match(normalize(value))
    if not match:
        raise GeoInputError.with_example(
            got=value,
            problem="Not a valid USNG/MGRS grid reference.",
            example=_EXAMPLE,
        )
    digits = match.group(2) or ""
    if len(digits) % 2 != 0:
        raise GeoInputError.with_example(
            got=value,
            problem=(
                f"A grid reference needs an even number of digits after the 100km "
                f"square (easting and northing must have equal length); "
                f"got {len(digits)}."
            ),
            example="10S GJ 0683 4468  (4 digits = 10m precision)",
        )
    try:
        return PRECISION_METRES[len(digits)]
    except KeyError:
        raise GeoInputError.with_example(
            got=value,
            problem=f"Grid references carry up to 10 digits of precision; got {len(digits)}.",
            example="10S GJ 06832 44683",
        ) from None


def _to_full_precision(value: str) -> str:
    """Expand a reference to its 10-digit form, naming the square's SW corner.

    ``'31UDQ4821'`` is a 1 km square with easting 48 and northing 21; its
    south-west corner is easting 48000, northing 21000. Right-padding each half
    to five digits is that same statement in string form.

    Done here rather than left to the parser because a bare 100 km square has no
    digits at all, and because it makes the corner semantics explicit instead of
    depending on how a library rounds.
    """
    match = _GRID_RE.match(normalize(value))
    assert match is not None  # precision_of() has already validated the shape
    square, digits = match.group(1), match.group(2) or ""
    half = len(digits) // 2
    return square + digits[:half].ljust(5, "0") + digits[half:].ljust(5, "0")


def to_latlon(value: str) -> tuple[float, float]:
    """Convert a USNG/MGRS reference to WGS84 ``(latitude, longitude)``.

    The returned point is the **south-west corner** of the named square, not
    its centre -- this is what the standard specifies, and callers working at
    coarse precision should be told which corner they got.
    """
    precision_of(value)  # raises with a helpful message if malformed
    try:
        point = parseMGRS(_to_full_precision(value)).toLatLon(center=False)
    except Exception as exc:
        raise GeoInputError.with_example(
            got=value,
            problem=f"Grid reference conversion failed ({exc}).",
            example=_EXAMPLE,
        ) from exc
    return float(point.lat), float(point.lon)


def from_latlon(lat: float, lon: float, digits: int = 10) -> str:
    """Convert WGS84 coordinates to a USNG/MGRS reference.

    ``digits`` is the total digit count (2, 4, 6, 8 or 10); 10 gives 1 m
    precision. Expressing it this way matches how grid references are written
    and read aloud, rather than as the 1-5 "precision level" the underlying
    libraries take.
    """
    if digits not in PRECISION_METRES or digits == 0:
        raise GeoInputError.with_example(
            got=digits,
            problem="Grid digit count must be one of 2, 4, 6, 8 or 10.",
            example="10  (for 1-metre precision)",
        )
    try:
        reference = toMgrs(toUtmUps8(lat, lon))
        square = reference.toStr(prec=0, sep="")[:-10]
        easting, northing = reference.easting, reference.northing
    except Exception as exc:
        raise GeoInputError.with_example(
            got=(lat, lon),
            problem=f"Could not express this position on the grid ({exc}).",
            example="48.8584, 2.2945",
        ) from exc
    # Truncate, never round. A reference names the square a position falls in,
    # so dropping digits must move the point to the coarser square's corner, not
    # to whichever neighbouring square happens to be closer.
    #
    # _RESIDUE_M absorbs projection residue before that truncation. Converting a
    # reference to coordinates and straight back lands a micrometre *below* the
    # square's own edge -- 48251.999999 rather than 48252 -- and a bare truncation
    # would then name the square next door.
    step = PRECISION_METRES[digits]
    half = digits // 2
    e = min(int((easting + _RESIDUE_M) // step), 100_000 // step - 1)
    n = min(int((northing + _RESIDUE_M) // step), 100_000 // step - 1)
    return f"{square}{e:0{half}d}{n:0{half}d}"
