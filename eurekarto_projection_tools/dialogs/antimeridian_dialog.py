# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QLabel
from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from .base import ToolDialog
from ..antimeridian import central_meridian
from ..common import tr


class AntimeridianDialog(ToolDialog):
    def __init__(self, iface, crs, callback):
        super().__init__(iface.mainWindow(), 'Antimeridian Cutter', callback)
        self.mode = QComboBox()
        self.mode.addItems([tr('Single layer'), tr('All project vector layers')])
        self.form.addRow(tr('Mode'), self.mode)
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(Qgis.LayerFilter.HasGeometry)
        self.layer.setLayer(iface.activeLayer())
        self.form.addRow(tr('Layer'), self.layer)
        self.width = self.number('Cut half-width (degrees)', 0.1, 0.000001, 20, 6)
        self.step = self.number('Mask densification step (degrees)', 0.5, 0.05, 10)
        self.manual = QCheckBox(tr('Override central meridian (WGS84 longitude)'))
        self.form.addRow(self.manual)
        self.meridian = self.number('Central meridian (degrees)', 0, -180, 180, 6)
        try:
            self.meridian.setValue(central_meridian(crs))
        except Exception as error:
            self.manual.setChecked(True)
            self.log.appendPlainText(str(error))
        self.add_mask = QCheckBox(tr('Add mask'))
        self.hide_originals = QCheckBox(tr('Hide original layers'))
        self.form.addRow(self.add_mask)
        self.form.addRow(self.hide_originals)
        note = QLabel(tr('Outputs are temporary layers in “New layers”. Export them to keep them.'))
        note.setWordWrap(True)
        self.form.addRow(note)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.manual.toggled.connect(self.update_controls)
        self.update_controls()

    def update_controls(self, *args):
        self.layer.setEnabled(self.mode.currentIndex() == 0)
        self.meridian.setEnabled(self.manual.isChecked())
