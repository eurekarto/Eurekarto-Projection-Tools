# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""The cap of the globe a projection can actually show, as rings in WGS 84.

An azimuthal projection shows what lies within a given angular distance of its
centre: half the globe for the orthographic, less for the gnomonic or a vertical
perspective. Beyond that horizon nothing tears — the far side simply folds over
or vanishes — so there is no tear to find and nothing to cut along. The remedy
is to keep only the cap, and that cap is a circle on the sphere, computed here
from the centre and the radius alone.

Written from the spherical formulae rather than adapted from Johannes Duguè's
ClipToHemisphere plugin, which solves the same problem for the hemisphere.
"""
import math
import re

MINIMUM_RADIUS, MAXIMUM_RADIUS = 1.0, 179.0
MINIMUM_STEP, MAXIMUM_STEP = 0.1, 10.0
# Distance kept from the horizon: exactly on it, a projection often refuses the
# point or places it at infinity.
INSET = 0.01


def point_at(latitude, longitude, radius, azimuth):
    """The point at an angular distance radius from a centre, along an azimuth."""
    phi, lam = math.radians(latitude), math.radians(longitude)
    angle, bearing = math.radians(radius), math.radians(azimuth)
    sin_phi = math.sin(phi) * math.cos(angle) + math.cos(phi) * math.sin(angle) * math.cos(bearing)
    sin_phi = max(-1.0, min(1.0, sin_phi))
    latitude_out = math.asin(sin_phi)
    longitude_out = lam + math.atan2(
        math.sin(bearing) * math.sin(angle) * math.cos(phi),
        math.cos(angle) - math.sin(phi) * sin_phi)
    return math.degrees(latitude_out), (math.degrees(longitude_out) + 540.0) % 360.0 - 180.0


def contains_pole(latitude, radius, sign):
    """True when the cap reaches the north (sign 1) or south (sign -1) pole."""
    return sign * latitude + radius >= 90.0


def unwrapped(points):
    """Longitudes made continuous, so a ring crossing ±180° can be reasoned about."""
    result, shift = [], 0.0
    previous = points[0][0]
    for longitude, latitude in points:
        while longitude + shift - previous > 180.0:
            shift -= 360.0
        while longitude + shift - previous < -180.0:
            shift += 360.0
        previous = longitude + shift
        result.append((previous, latitude))
    return result


def cap_rings(latitude, longitude, radius, step=1.0):
    """The cap as one or two rings of (longitude, latitude), ready to clip with.

    A cap holding a pole cannot be written as a simple ring in longitude and
    latitude: its boundary runs right round the globe, and the polygon has to be
    closed along the top or bottom edge of the map. A cap crossing the date line
    is split in two instead.
    """
    radius = max(MINIMUM_RADIUS, min(radius, MAXIMUM_RADIUS)) - INSET
    count = max(int(round(360.0 / step)), 8)
    boundary = [point_at(latitude, longitude, radius, azimuth * 360.0 / count)
                for azimuth in range(count)]
    ring = unwrapped([(lon, lat) for lat, lon in boundary])
    north = contains_pole(latitude, radius, 1)
    south = contains_pole(latitude, radius, -1)
    if north or south:
        edge = 90.0 if north else -90.0
        ordered = sorted(((lon + 540.0) % 360.0 - 180.0, lat) for lon, lat in ring)
        ordered = [(-180.0, ordered[0][1])] + ordered + [(180.0, ordered[-1][1])]
        return [ordered + [(180.0, edge), (-180.0, edge)]]
    spans = max(lon for lon, _ in ring) - min(lon for lon, _ in ring)
    if spans <= 360.0 and any(abs(lon) > 180.0 for lon, _ in ring):
        # The ring crosses the date line: cut it into an eastern and a western part.
        east = [((lon + 540.0) % 360.0 - 180.0, lat) for lon, lat in ring]
        return split_ring(east)
    return [[((lon + 540.0) % 360.0 - 180.0, lat) for lon, lat in ring]]


def split_ring(ring):
    """Split a ring that crosses ±180° into the eastern and the western piece."""
    east, west = [], []
    for index, (longitude, latitude) in enumerate(ring):
        following = ring[(index + 1) % len(ring)]
        (east if longitude >= 0 else west).append((longitude, latitude))
        if (longitude >= 0) != (following[0] >= 0) and abs(longitude - following[0]) > 180.0:
            crossing = (latitude + following[1]) / 2.0
            if longitude >= 0:
                east.append((180.0, crossing))
                west.append((-180.0, crossing))
            else:
                west.append((-180.0, crossing))
                east.append((180.0, crossing))
    return [piece for piece in (east, west) if len(piece) >= 3]


def centre_from_proj(proj):
    """The centre of an azimuthal projection, read from its PROJ definition.

    Defaults to 0°, 0° when a parameter is absent, as PROJ itself does.
    """
    def parameter(name):
        found = re.search(r'(?:^|\s)\+{0}=(-?\d+(?:\.\d+)?)'.format(name), proj or '')
        return float(found.group(1)) if found else 0.0

    latitude = parameter('lat_0')
    longitude = parameter('lon_0')
    return max(-90.0, min(90.0, latitude)), (longitude + 540.0) % 360.0 - 180.0
