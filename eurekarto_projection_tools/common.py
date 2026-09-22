# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared Processing execution, cancellation and validation."""
import math
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsProcessingException, QgsVectorLayer
import processing


def tr(text):
    return QCoreApplication.translate('EurekartoProjectionTools', text)


class Cancelled(Exception):
    pass


def check_cancel(feedback):
    if feedback.isCanceled():
        raise Cancelled()


def run(algorithm, parameters, context, feedback):
    check_cancel(feedback)
    previous_errors = len(getattr(feedback, 'errors', []))
    try:
        result = processing.run(algorithm, dict(parameters, OUTPUT='TEMPORARY_OUTPUT'),
                                context=context, feedback=feedback)['OUTPUT']
    except Exception:
        check_cancel(feedback)
        raise
    check_cancel(feedback)
    errors = getattr(feedback, 'errors', [])[previous_errors:]
    if errors:
        raise QgsProcessingException('\n'.join(errors))
    if not isinstance(result, QgsVectorLayer) or not result.isValid():
        raise QgsProcessingException(tr('Processing did not return a valid vector layer.'))
    return result


def validate_crs(crs):
    if not crs.isValid():
        raise QgsProcessingException(tr('The coordinate reference system is invalid.'))


def bounded(value, minimum, maximum):
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise QgsProcessingException(tr('A numeric parameter is outside its allowed range.'))


def carry_style(source, result):
    """Give the result the look of the layer it came from: symbology and labels.

    The cut returns a new layer, which QGIS would otherwise draw with a random
    default colour. Kept in one place so every tool carries the style the same way.
    """
    if source.renderer():
        result.setRenderer(source.renderer().clone())
    if source.labeling():
        result.setLabeling(source.labeling().clone())
        result.setLabelsEnabled(source.labelsEnabled())
    return result
