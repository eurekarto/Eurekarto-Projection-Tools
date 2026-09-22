# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""Find where a projection tears, by projecting a grid rather than assuming an aspect.

The antimeridian tool knows where to cut because it reads the central meridian
from the CRS. That reasoning holds only for a projection in the normal aspect. A
transverse projection tears along the far half of the equator, an oblique one
along another great circle, an interrupted one along several lines at once. Here
nothing is assumed: a grid is projected and each cell is compared with its own
neighbours.

Comparing against the whole map would confuse a tear with a stretch: in a conic
projection the far hemisphere is enormous but continuous, and a global threshold
would cut it away. A tear is local — the cell sitting on it blows up while the
cells beside it do not.
"""
import math

MINIMUM_STEP, MAXIMUM_STEP = 0.25, 5.0
MINIMUM_FACTOR, MAXIMUM_FACTOR = 5.0, 1000.0
DEFAULT_FACTOR = 20.0
# Neighbours consulted on each side, along the row and along the column.
REACH = 2


def cell_bounds(step, offset=0.0):
    """Every grid cell, plus one column straddling the date line.

    A grid that starts at -180° never straddles the date line, so the tear of an
    ordinary world projection would fall exactly between two cells and go
    unseen. The extra column covers it; its longitudes run past 180°, which is
    what the split below resolves. The offset shifts the whole grid, which is how
    the second pass catches a tear sitting on the lines of the first.
    """
    columns = int(math.ceil(360.0 / step))
    rows = int(math.ceil((180.0 - offset) / step))
    cells = []
    for row in range(rows):
        south = -90.0 + offset + row * step
        north = min(south + step, 90.0)
        for column in range(columns):
            west = -180.0 + offset + column * step
            cells.append((west, west + step, south, north))
        cells.append((180.0 - step / 2.0, 180.0 + step / 2.0, south, north))
    return cells, columns + 1, rows


def split_at_date_line(west, east):
    """A cell as one or two longitude spans, none of them crossing ±180°."""
    if west < -180.0:
        return [(-180.0, east), (west + 360.0, 180.0)]
    if east <= 180.0:
        return [(west, east)]
    return [(west, 180.0), (-180.0, east - 360.0)]


def longest_side(points):
    """The longest projected side of a cell, or None when a corner has no image."""
    if any(point is None for point in points):
        return None
    longest = 0.0
    for index, (x, y) in enumerate(points):
        following_x, following_y = points[(index + 1) % len(points)]
        side = math.hypot(following_x - x, following_y - y)
        if not math.isfinite(side):
            return None
        longest = max(longest, side)
    return longest


def median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else None


def local_reference(sides, columns, rows, column, row, fallback):
    """The scale around a cell: the quieter of its row and its column.

    A tear runs along a line, so the cells following it are torn as well. Taking
    the smaller of the two medians keeps one direction clear of the tear, and
    that is the direction that reveals it.
    """
    references = []
    for step_column, step_row in ((1, 0), (0, 1)):
        neighbours = []
        for offset in range(-REACH, REACH + 1):
            if offset == 0:
                continue
            other_column = (column + offset * step_column) % columns
            other_row = row + offset * step_row
            if not 0 <= other_row < rows:
                continue
            side = sides[other_column][other_row]
            if side is not None:
                neighbours.append(side)
        if neighbours:
            references.append(median(neighbours))
    return min(references) if references else fallback


def torn_cells(project, step=1.0, factor=DEFAULT_FACTOR):
    """Grid cells straddling a tear, as longitude spans with their latitudes.

    project takes a list of (longitude, latitude) and returns a list of (x, y),
    or None for a point the projection cannot place.

    Two grids are projected, the second shifted by half a cell. A tear falling
    exactly on the lines of one grid is invisible to it — no cell straddles it —
    but it cannot fall on the lines of both.
    """
    found = []
    for offset in (0.0, step / 2.0):
        for cell in single_pass(project, step, factor, offset):
            if cell not in found:
                found.append(cell)
    return found


def single_pass(project, step, factor, offset):
    cells, columns, rows = cell_bounds(step, offset)
    corners = []
    for west, east, south, north in cells:
        corners += [(west, south), (east, south), (east, north), (west, north)]
    projected = project(corners)
    sides = [[None] * rows for _ in range(columns)]
    measured = []
    for index, _ in enumerate(cells):
        column, row = index % columns, index // columns
        side = longest_side(projected[index * 4:index * 4 + 4])
        sides[column][row] = side
        if side is not None:
            measured.append(side)
    if not measured:
        return []
    fallback = median(measured)
    torn = []
    for index, (west, east, south, north) in enumerate(cells):
        column, row = index % columns, index // columns
        side = sides[column][row]
        reference = local_reference(sides, columns, rows, column, row, fallback)
        if side is None or side > reference * factor:
            for left, right in split_at_date_line(west, east):
                torn.append((left, right, south, north))
    return torn
