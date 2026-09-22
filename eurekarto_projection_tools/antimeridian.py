# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cut vector layers along the meridian opposite the projection's central one.

The workflow is: repair geometries, reproject to EPSG:4326, subtract a densified
band centred on the antipodal meridian, then reproject to the project CRS. The
cut happens in geographic coordinates because that is where the band is a simple
rectangle.
"""
import math
import re
from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsProcessingException, QgsVectorLayer, Qgis)
from .common import bounded, carry_style, check_cancel, run, tr, validate_crs


def normalize_longitude(value):
    return (value + 180.0) % 360.0 - 180.0


def central_meridian(crs):
    validate_crs(crs)
    proj = crs.toProj()
    # Non-Greenwich prime meridians need an explicit WGS84 longitude.
    pm = re.search(r'(?:^|\s)\+pm=([^\s]+)', proj)
    if pm and pm.group(1) not in ('0', '0.0', 'greenwich'):
        raise QgsProcessingException(tr('Set the central meridian manually for this CRS.'))
    match = re.search(r'(?:^|\s)\+lon_0=([^\s]+)', proj)
    if match:
        try:
            value = float(match.group(1))
            if math.isfinite(value):
                return normalize_longitude(value)
        except ValueError:
            pass
    zone = re.search(r'(?:^|\s)\+zone=(\d+)', proj)
    if zone and 1 <= int(zone.group(1)) <= 60:
        return int(zone.group(1)) * UTM_ZONE_WIDTH + UTM_FIRST_MERIDIAN
    if crs.isGeographic():
        return 0.0
    raise QgsProcessingException(
        tr('The central meridian could not be detected. Enable the manual override.'))


# The displayed mask stops short of the poles: a band reaching exactly ±90° can
# produce an invalid geometry once reprojected for display in an interrupted
# projection. The cut itself also removes both polar caps beyond that limit: left
# in place, a cap bridges the two sides of the band, and in a conic or azimuthal
# projection — where a pole becomes a point or recedes to infinity — Antarctica
# then closes into a ring that wraps around the whole map.
POLAR_LIMIT = 89.9
MINIMUM_HALF_WIDTH, MAXIMUM_HALF_WIDTH = 0.000001, 20.0
MINIMUM_STEP, MAXIMUM_STEP = 0.05, 10.0
# UTM zone 1 is centred on -177°, each zone spanning 6°.
UTM_ZONE_WIDTH, UTM_FIRST_MERIDIAN = 6.0, -183.0


def mask_intervals(antipode, half_width):
    bounded(half_width, MINIMUM_HALF_WIDTH, MAXIMUM_HALF_WIDTH)
    antipode = normalize_longitude(antipode)
    left, right = antipode - half_width, antipode + half_width
    if left < -180.0:
        return [(-180.0, right), (left + 360.0, 180.0)]
    if right > 180.0:
        return [(left, 180.0), (-180.0, right - 360.0)]
    return [(left, right)]


def create_mask(antipode, half_width=0.1, step=0.5):
    bounded(step, MINIMUM_STEP, MAXIMUM_STEP)
    layer = QgsVectorLayer('Polygon?crs=EPSG:4326', tr('Antipodal mask'), 'memory')
    span = 2 * POLAR_LIMIT
    count = math.ceil(span / step)
    latitudes = [-POLAR_LIMIT + min(i * step, span) for i in range(count + 1)]
    for left, right in mask_intervals(antipode, half_width):
        ring = [QgsPointXY(left, lat) for lat in latitudes]
        ring += [QgsPointXY(right, lat) for lat in reversed(latitudes)]
        ring.append(ring[0])
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPolygonXY([ring]))
        if not layer.dataProvider().addFeature(feature):
            raise QgsProcessingException(tr('Could not create the mask.'))
    layer.updateExtents()
    return layer


def polar_caps():
    """The two latitude intervals beyond POLAR_LIMIT, south then north."""
    return [(-90.0, -POLAR_LIMIT), (POLAR_LIMIT, 90.0)]


def cap_ring(south, north, step):
    """A polar cap as a closed ring, with a vertex every step degrees of longitude.

    Reprojection moves vertices and nothing else: an edge spanning 360° of
    longitude with two vertices becomes a straight chord across the map, and the
    feature cut against it inherits that chord. Densified like the band, the edge
    follows its parallel.
    """
    count = math.ceil(360.0 / step)
    longitudes = [-180.0 + min(index * step, 360.0) for index in range(count + 1)]
    ring = [(longitude, north) for longitude in longitudes]
    ring += [(longitude, south) for longitude in reversed(longitudes)]
    ring.append(ring[0])
    return ring


def cutting_mask(mask, step=0.5):
    """The displayed band plus both polar caps: what the layers are actually cut with.

    Cutting along the band alone leaves each polar cap joining the two sides of
    the cut, so a feature around a pole stays in one piece across the date line.
    """
    bounded(step, MINIMUM_STEP, MAXIMUM_STEP)
    layer = QgsVectorLayer('Polygon?crs=EPSG:4326', tr('Antipodal mask'), 'memory')
    features = [QgsFeature(feature) for feature in mask.getFeatures()]
    for south, north in polar_caps():
        cap = QgsFeature()
        cap.setGeometry(QgsGeometry.fromPolygonXY(
            [[QgsPointXY(x, y) for x, y in cap_ring(south, north, step)]]))
        features.append(cap)
    if not layer.dataProvider().addFeatures(features)[0]:
        raise QgsProcessingException(tr('Could not create the mask.'))
    layer.updateExtents()
    return layer


def cut_layer(layer, mask, target_crs, context, feedback):
    validate_crs(target_crs)
    if not layer or not layer.isValid() or not layer.isSpatial():
        raise QgsProcessingException(tr('Select a valid spatial vector layer.'))
    validate_crs(layer.crs())
    check_cancel(feedback)
    fixed = layer
    if layer.geometryType() in (Qgis.GeometryType.Line, Qgis.GeometryType.Polygon):
        feedback.pushInfo(tr('Repairing geometries…'))
        fixed = run('native:fixgeometries', {'INPUT': layer, 'METHOD': 0}, context, feedback)
    geographic = QgsCoordinateReferenceSystem('EPSG:4326')
    feedback.pushInfo(tr('Reprojecting to EPSG:4326…'))
    if fixed.crs() != geographic:
        fixed = run('native:reprojectlayer', {'INPUT': fixed, 'TARGET_CRS': geographic},
                    context, feedback)
    feedback.pushInfo(tr('Cutting the antipodal band…'))
    result = run('native:difference', {'INPUT': fixed, 'OVERLAY': mask}, context, feedback)
    # native:difference leaves empty records behind on QGIS 3.40; drop them.
    result = run('native:removenullgeometries', {'INPUT': result, 'REMOVE_EMPTY': True},
                 context, feedback)
    feedback.pushInfo(tr('Reprojecting to the project CRS…'))
    if result.crs() != target_crs:
        result = run('native:reprojectlayer', {'INPUT': result, 'TARGET_CRS': target_crs},
                     context, feedback)
    result.setName(layer.name() + ' Projection Tool')
    return carry_style(layer, result)
