# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""Turn the geometry worked out by seams and horizon into layers QGIS can cut with.

The two modules beside this one hold arithmetic alone, with no QGIS in sight, so
they can be tested against PROJ outside the application. Everything that needs
QGIS lives here.
"""
import math

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsCsException, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsProcessingException, QgsVectorLayer)

from . import horizon, seams
from .common import bounded, carry_style, check_cancel, run, tr, validate_crs

GEOGRAPHIC = 'EPSG:4326'


def rings_layer(rings, name):
    """A memory layer in WGS 84 holding one polygon per ring."""
    layer = QgsVectorLayer('Polygon?crs=' + GEOGRAPHIC, name, 'memory')
    features = []
    for ring in rings:
        points = [QgsPointXY(longitude, latitude) for longitude, latitude in ring]
        if points[0] != points[-1]:
            points.append(points[0])
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
        features.append(feature)
    if not features or not layer.dataProvider().addFeatures(features)[0]:
        raise QgsProcessingException(tr('Could not create the mask.'))
    layer.updateExtents()
    return layer


def projector(target_crs, context):
    """A function projecting WGS 84 points, answering None where there is no image."""
    transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem(GEOGRAPHIC),
                                       target_crs, context.transformContext())

    def project(points):
        projected = []
        for longitude, latitude in points:
            try:
                point = transform.transform(QgsPointXY(longitude, latitude))
            except QgsCsException:
                projected.append(None)
                continue
            x, y = point.x(), point.y()
            projected.append((x, y) if math.isfinite(x) and math.isfinite(y) else None)
        return projected

    return project


def tear_mask(target_crs, step, factor, context, feedback):
    """The cells the projection tears along, as a layer to subtract from the data."""
    validate_crs(target_crs)
    bounded(step, seams.MINIMUM_STEP, seams.MAXIMUM_STEP)
    bounded(factor, seams.MINIMUM_FACTOR, seams.MAXIMUM_FACTOR)
    feedback.pushInfo(tr('Projecting the grid to find the tears…'))
    cells = seams.torn_cells(projector(target_crs, context), step, factor)
    check_cancel(feedback)
    if not cells:
        raise QgsProcessingException(tr(
            'No tear was found in this projection. Nothing needs cutting; if a feature '
            'still stretches across the map, lower the sensitivity.'))
    longitudes = sorted({round((west + east) / 2, 3) for west, east, _, _ in cells})
    latitudes = sorted({round((south + north) / 2, 3) for _, _, south, north in cells})
    feedback.pushInfo(tr('Tears found in {0} cells, between {1}° and {2}° of longitude '
                         'and {3}° and {4}° of latitude.').format(
                             len(cells), longitudes[0], longitudes[-1],
                             latitudes[0], latitudes[-1]))
    rings = [[(west, south), (east, south), (east, north), (west, north)]
             for west, east, south, north in cells]
    layer = rings_layer(rings, tr('Tear mask'))
    return run('native:dissolve', {'INPUT': layer, 'FIELD': []}, context, feedback)


def horizon_mask(latitude, longitude, radius, step, feedback):
    """The cap of the globe the projection can show, as a layer to clip the data to."""
    bounded(radius, horizon.MINIMUM_RADIUS, horizon.MAXIMUM_RADIUS)
    bounded(step, horizon.MINIMUM_STEP, horizon.MAXIMUM_STEP)
    bounded(latitude, -90.0, 90.0)
    bounded(longitude, -180.0, 180.0)
    rings = horizon.cap_rings(latitude, longitude, radius, step)
    if not rings:
        raise QgsProcessingException(tr('Could not build the horizon.'))
    feedback.pushInfo(tr('Horizon: {0}° around {1}°, {2}°.').format(radius, latitude, longitude))
    return rings_layer(rings, tr('Horizon mask'))


def prepared(layer, context, feedback):
    """A repaired copy of the layer in WGS 84, ready for an overlay operation."""
    if not layer or not layer.isValid() or not layer.isSpatial():
        raise QgsProcessingException(tr('Select a valid spatial vector layer.'))
    validate_crs(layer.crs())
    check_cancel(feedback)
    fixed = layer
    if layer.geometryType() in (Qgis.GeometryType.Line, Qgis.GeometryType.Polygon):
        feedback.pushInfo(tr('Repairing geometries…'))
        fixed = run('native:fixgeometries', {'INPUT': layer, 'METHOD': 0}, context, feedback)
    geographic = QgsCoordinateReferenceSystem(GEOGRAPHIC)
    if fixed.crs() != geographic:
        feedback.pushInfo(tr('Reprojecting to EPSG:4326…'))
        fixed = run('native:reprojectlayer', {'INPUT': fixed, 'TARGET_CRS': geographic},
                    context, feedback)
    return fixed


def overlay_layer(layer, mask, target_crs, algorithm, message, context, feedback):
    """Cut or clip one layer against a mask, and hand it back in the project CRS."""
    validate_crs(target_crs)
    fixed = prepared(layer, context, feedback)
    feedback.pushInfo(message)
    result = run(algorithm, {'INPUT': fixed, 'OVERLAY': mask}, context, feedback)
    # Overlays leave empty records behind on QGIS 3.40; drop them.
    result = run('native:removenullgeometries', {'INPUT': result, 'REMOVE_EMPTY': True},
                 context, feedback)
    if result.crs() != target_crs:
        feedback.pushInfo(tr('Reprojecting to the project CRS…'))
        result = run('native:reprojectlayer', {'INPUT': result, 'TARGET_CRS': target_crs},
                     context, feedback)
    result.setName(layer.name() + ' Projection Tool')
    return carry_style(layer, result)


def cut_along_tears(layer, mask, target_crs, context, feedback):
    return overlay_layer(layer, mask, target_crs, 'native:difference',
                         tr('Cutting along the tears…'), context, feedback)


def clip_to_horizon(layer, mask, target_crs, context, feedback):
    return overlay_layer(layer, mask, target_crs, 'native:clip',
                         tr('Clipping to the horizon…'), context, feedback)
