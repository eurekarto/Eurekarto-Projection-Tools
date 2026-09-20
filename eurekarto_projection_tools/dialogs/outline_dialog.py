# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
from qgis.PyQt.QtWidgets import QComboBox, QLabel
from qgis.core import Qgis, QgsUnitTypes
from .base import ToolDialog
from ..common import tr


class OutlineDialog(ToolDialog):
    def __init__(self, iface, crs, callback):
        super().__init__(iface.mainWindow(), 'Projection Outline', callback)
        self.output_type = QComboBox()
        self.output_type.addItems([tr('Contour - Line'), tr('Contour - Polygon')])
        self.form.addRow(tr('Output type'), self.output_type)
        self.step = self.number('Grid step (degrees)', 1.0, 0.25, 5.0, 2)
        unit = QgsUnitTypes.toString(crs.mapUnits())
        factor = QgsUnitTypes.fromUnitToUnitFactor(Qgis.DistanceUnit.Meters, crs.mapUnits())
        default_edge = 5.0 if crs.isGeographic() else 500000.0 * factor
        self.edge = self.number('Maximum projected edge length', default_edge, 0.000001, 1e12, 6)
        self.form.addRow(tr('Project CRS units'), QLabel(unit))
        note = QLabel(tr(
            'Approximate contour: cells crossing projection interruptions are rejected. '
            'Adjust the grid step and edge threshold together. Outputs are temporary.'))
        note.setWordWrap(True)
        self.form.addRow(note)
