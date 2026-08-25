"""Pure geospatial computation.

Nothing in this subpackage touches the network, the filesystem or the clock.
Every function is deterministic and directly unit-testable, which is what makes
the golden-vector tests in ``tests/geo/`` meaningful.
"""
