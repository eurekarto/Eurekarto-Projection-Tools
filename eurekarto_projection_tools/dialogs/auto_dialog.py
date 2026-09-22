# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QLabel
from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from .base import ToolDialog
from ..common import tr


class AutoDialog(ToolDialog):
    def __init__(self, iface, crs, callback):
        super().__init__(iface.mainWindow(), 'Auto Cutter', callback)
        self.mode = QComboBox()
        self.mode.addItems([tr('Single layer'), tr('All project vector layers')])
        self.form.addRow(tr('Mode'), self.mode)
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(Qgis.LayerFilter.HasGeometry)
        self.layer.setLayer(iface.activeLayer())
        self.form.addRow(tr('Layer'), self.layer)
        self.step = self.number('Grid step (degrees)', 1.0, 0.25, 5.0, 2)
        self.factor = self.number('Sensitivity (times the local scale)', 20.0, 5.0, 1000.0, 1)
        self.add_mask = QCheckBox(tr('Add mask'))
        self.hide_originals = QCheckBox(tr('Hide original layers'))
        self.form.addRow(self.add_mask)
        self.form.addRow(self.hide_originals)
        note = QLabel(tr(
            'The tears are found by projecting a grid, so no aspect is assumed. The cut is '
            'one grid cell wide; for a projection in the normal aspect the antimeridian '
            'tool cuts more finely. Outputs are temporary.'))
        note.setWordWrap(True)
        self.form.addRow(note)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.update_controls()

    def update_controls(self, *args):
        self.layer.setEnabled(self.mode.currentIndex() == 0)
