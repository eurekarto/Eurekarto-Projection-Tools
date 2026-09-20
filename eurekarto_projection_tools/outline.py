# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""Approximate a projection domain by transforming and dissolving grid cells.

A global geographic grid is transformed into the project CRS cell by cell. Cells
that cannot be transformed, that collapse, or whose projected edges exceed a
threshold are rejected: those are the cells straddling an interruption or the
edge of the projection. What remains, dissolved, approximates the domain.
"""
import math
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException,
                       QgsFeature, QgsGeometry, QgsPointXY, QgsProcessingException,
                       QgsVectorLayer)
from .common import bounded, check_cancel, run, tr, validate_crs

# The grid stops just short of the poles, where many projections are singular.
POLAR_LIMIT = 89.999
MINIMUM_STEP, MAXIMUM_STEP = 0.25, 5.0
MINIMUM_EDGE, MAXIMUM_EDGE = 0.000001, 1e12
# Features are written by batches to keep memory use flat on fine grids.
BATCH_SIZE = 5000
# Share of the progress bar spent building the grid; the rest is the dissolve.
GRID_SHARE = 70.0


def transformed_row(transform, longitudes, latitude):
    """One row of grid vertices in the target CRS; None where the CRS has no answer."""
    points = []
    for longitude in longitudes:
        try:
            point = transform.transform(QgsPointXY(longitude, latitude))
        except QgsCsException:
            points.append(None)
            continue
        points.append(point if math.isfinite(point.x()) and math.isfinite(point.y()) else None)
    return points


def cell_geometry(points, max_edge):
    """The cell as a polygon, or None when it must be rejected.

    A cell is rejected when a corner has no image in the target CRS, when one of
    its projected edges is longer than max_edge — the signature of a cell
    straddling an interruption — or when the polygon collapses.
    """
    if any(point is None for point in points):
        return None
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        if math.hypot(point.x() - following.x(), point.y() - following.y()) > max_edge:
            return None
    geometry = QgsGeometry.fromPolygonXY([points + [points[0]]])
    if geometry.isEmpty() or geometry.area() <= 0 or not geometry.isGeosValid():
        return None
    return geometry


def grid_layer(target_crs, transform, step, max_edge, feedback):
    """A memory layer of every usable cell, with the accepted and rejected counts."""
    # setCrs retains custom projections with no authority identifier.
    cells = QgsVectorLayer('Polygon', 'Projection cells', 'memory')
    cells.setCrs(target_crs)
    provider = cells.dataProvider()
    span = 2 * POLAR_LIMIT
    columns, rows = math.ceil(360.0 / step), math.ceil(span / step)
    longitudes = [-180.0 + min(index * step, 360.0) for index in range(columns + 1)]

    def flush(features):
        if features and not provider.addFeatures(features)[0]:
            raise QgsProcessingException(tr('Could not create the projection grid.'))

    lower = transformed_row(transform, longitudes, -POLAR_LIMIT)
    features, accepted, rejected = [], 0, 0
    feedback.pushInfo(tr('Building the projection grid…'))
    for row in range(rows):
        check_cancel(feedback)
        upper = transformed_row(transform, longitudes,
                                -POLAR_LIMIT + min((row + 1) * step, span))
        for column in range(columns):
            geometry = cell_geometry(
                [lower[column], lower[column + 1], upper[column + 1], upper[column]], max_edge)
            if geometry is None:
                rejected += 1
                continue
            feature = QgsFeature()
            feature.setGeometry(geometry)
            features.append(feature)
            accepted += 1
            if len(features) >= BATCH_SIZE:
                flush(features)
                features = []
        lower = upper
        feedback.setProgress(GRID_SHARE * (row + 1) / rows)
    flush(features)
    cells.updateExtents()
    return cells, accepted, rejected


def projection_outline(target_crs, step, max_edge, as_line, context, feedback):
    """The outline of the projection domain, as a line or a polygon layer."""
    validate_crs(target_crs)
    bounded(step, MINIMUM_STEP, MAXIMUM_STEP)
    bounded(max_edge, MINIMUM_EDGE, MAXIMUM_EDGE)
    transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),
                                       target_crs, context.transformContext())
    cells, accepted, rejected = grid_layer(target_crs, transform, step, max_edge, feedback)
    check_cancel(feedback)
    feedback.pushInfo(tr('Accepted cells: {0}; rejected cells: {1}.').format(accepted, rejected))
    if not accepted:
        raise QgsProcessingException(
            tr('No valid cells. Adjust the grid step or maximum edge length.'))
    feedback.pushInfo(tr('Dissolving the projection domain…'))
    domain = run('native:dissolve', {'INPUT': cells, 'FIELD': []}, context, feedback)
    domain = run('native:fixgeometries', {'INPUT': domain, 'METHOD': 0}, context, feedback)
    result = run('native:boundary', {'INPUT': domain}, context, feedback) if as_line else domain
    if result.featureCount() == 0:
        raise QgsProcessingException(tr('The projection outline is empty.'))
    result.setName('Contour - Line' if as_line else 'Contour - Polygon')
    feedback.setProgress(100)
    return result
