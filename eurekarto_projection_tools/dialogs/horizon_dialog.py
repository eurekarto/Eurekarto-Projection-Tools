# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QLabel
from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from .base import ToolDialog
from ..common import tr
from ..horizon import centre_from_proj


class HorizonDialog(ToolDialog):
    def __init__(self, iface, crs, callback):
        super().__init__(iface.mainWindow(), 'Horizon Cutter', callback)
        self.mode = QComboBox()
        self.mode.addItems([tr('Single layer'), tr('All project vector layers')])
        self.form.addRow(tr('Mode'), self.mode)
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(Qgis.LayerFilter.HasGeometry)
        self.layer.setLayer(iface.activeLayer())
        self.form.addRow(tr('Layer'), self.layer)
        self.radius = self.number('Horizon radius (degrees from the centre)', 90.0, 1.0, 179.0, 3)
        self.step = self.number('Horizon densification step (degrees)', 1.0, 0.1, 10.0, 2)
        self.manual = QCheckBox(tr('Override the projection centre (WGS84)'))
        self.form.addRow(self.manual)
        self.latitude = self.number('Centre latitude (degrees)', 0.0, -90.0, 90.0, 6)
        self.longitude = self.number('Centre longitude (degrees)', 0.0, -180.0, 180.0, 6)
        latitude, longitude = centre_from_proj(crs.toProj() if crs.isValid() else '')
        self.latitude.setValue(latitude)
        self.longitude.setValue(longitude)
        self.add_mask = QCheckBox(tr('Add mask'))
        self.hide_originals = QCheckBox(tr('Hide original layers'))
        self.form.addRow(self.add_mask)
        self.form.addRow(self.hide_originals)
        note = QLabel(tr(
            'Keeps only what the projection can show: the cap of the given radius around '
            'its centre. For an orthographic projection that is the visible hemisphere, 90°. '
            'Outputs are temporary.'))
        note.setWordWrap(True)
        self.form.addRow(note)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.manual.toggled.connect(self.update_controls)
        self.update_controls()

    def update_controls(self, *args):
        self.layer.setEnabled(self.mode.currentIndex() == 0)
        self.latitude.setEnabled(self.manual.isChecked())
        self.longitude.setEnabled(self.manual.isChecked())
