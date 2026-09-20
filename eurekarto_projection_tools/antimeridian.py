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
from .common import bounded, check_cancel, run, tr, validate_crs


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


# The mask stops short of the poles: a band reaching exactly ±90° can produce an
# invalid geometry once reprojected for display in an interrupted projection.
# The uncut residue is therefore POLAR_LIMIT degrees wide at each pole.
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
    if layer.renderer():
        result.setRenderer(layer.renderer().clone())
    if layer.labeling():
        result.setLabeling(layer.labeling().clone())
        result.setLabelsEnabled(layer.labelsEnabled())
    return result
