# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""QGIS plugin lifecycle and publication of completed output layers."""
from pathlib import Path
import traceback
from qgis.PyQt.QtCore import QCoreApplication, QLocale, QSettings, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMessageBox
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt 5
    from qgis.PyQt.QtWidgets import QAction
from qgis.core import (Qgis, QgsFillSymbol, QgsLineSymbol, QgsMessageLog, QgsProcessingContext,
                       QgsProcessingException, QgsProject, QgsVectorLayer)
from .antimeridian import (central_meridian, create_mask, cut_layer, cutting_mask,
                           normalize_longitude)
from .common import Cancelled, check_cancel, run, tr, validate_crs
from .dialogs.antimeridian_dialog import AntimeridianDialog
from .dialogs.outline_dialog import OutlineDialog
from .outline import projection_outline

VERSION = '1.0.4'
# Layer tree group receiving every output. Kept untranslated on purpose: it is
# looked up by name, and a language change must not orphan an existing group.
OUTPUT_GROUP = 'New layers'
MASK_FILL = {'color': '235,95,60,70', 'outline_color': '200,65,40,255'}
OUTLINE_LINE = {'line_color': '45,65,80', 'line_width': '0.35'}
OUTLINE_FILL = {'style': 'no', 'outline_color': '45,65,80'}


class EurekartoProjectionTools:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.dialog = None
        self.translator = None
        self.menu = 'Eurekarto Projection Tools'
        self.directory = Path(__file__).resolve().parent
        settings = QSettings()
        override = settings.value('locale/overrideFlag', False, type=bool)
        locale = settings.value('locale/userLocale', 'en') if override else QLocale().name()
        if str(locale).lower().startswith('fr'):
            translator = QTranslator()
            if translator.load(str(self.directory / 'i18n' / 'eurekarto_projection_tools_fr.qm')):
                QCoreApplication.installTranslator(translator)
                self.translator = translator

    # ------------------------------------------------------------------ lifecycle

    def initGui(self):
        icon = QIcon(str(self.directory / 'img' / 'icon.png'))
        for title, callback, on_toolbar in [
                ('Antimeridian Cutter', self.show_cutter, True),
                ('Projection Outline', self.show_outline, True),
                ('About', self.about, False)]:
            action = QAction(icon, tr(title), self.iface.mainWindow())
            action.triggered.connect(callback)
            self.iface.addPluginToMenu(self.menu, action)
            if on_toolbar:
                self.iface.addToolBarIcon(action)
            self.actions.append(action)

    def unload(self):
        if self.dialog:
            self.dialog.cancel()
            self.dialog.close()
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
            action.deleteLater()
        self.actions.clear()
        if self.translator:
            QCoreApplication.removeTranslator(self.translator)
            self.translator = None

    def show(self, dialog_class, callback):
        if self.dialog is not None:
            self.dialog.raise_()
            return
        self.dialog = dialog_class(self.iface, QgsProject.instance().crs(), callback)
        try:
            self.dialog.exec()
        finally:
            self.dialog.deleteLater()
            self.dialog = None

    def show_cutter(self):
        self.show(AntimeridianDialog, self.execute_cutter)

    def show_outline(self):
        self.show(OutlineDialog, self.execute_outline)

    def about(self):
        QMessageBox.about(self.iface.mainWindow(), self.menu,
                          '{0} {1}\n\n© 2026 Blanche Lambert / Eurêkarto\n{2}\n'
                          'GNU GPL v2 or later\nQGIS 3.40 LTR / QGIS 4.x'.format(
                              self.menu, VERSION,
                              tr('Created by Blanche Lambert for Eurêkarto in 2026.')))

    # --------------------------------------------------------------------- shared

    def context(self):
        project = QgsProject.instance()
        validate_crs(project.crs())
        context = QgsProcessingContext()
        context.setProject(project)
        return project, context

    def publish(self, layers, project):
        root = project.layerTreeRoot()
        group = root.findGroup(OUTPUT_GROUP) or root.insertGroup(0, OUTPUT_GROUP)
        for layer in layers:
            project.addMapLayer(layer, False)
            group.addLayer(layer)
        self.iface.mapCanvas().refresh()

    def error(self, dialog, error):
        dialog.feedback.pushInfo(tr('Error: {0}').format(error))
        QgsMessageLog.logMessage(traceback.format_exc(), self.menu, Qgis.MessageLevel.Warning)

    # ---------------------------------------------------------- antimeridian tool

    @staticmethod
    def chosen_layers(dialog, project):
        """The layer picked in the dialog, or every spatial vector layer of the project."""
        if dialog.mode.currentIndex() == 1:
            layers = [layer for layer in project.mapLayers().values()
                      if isinstance(layer, QgsVectorLayer) and layer.isValid()
                      and layer.isSpatial()]
        else:
            layers = [layer for layer in [dialog.layer.currentLayer()] if layer is not None]
        if not layers:
            raise QgsProcessingException(tr('Select a valid spatial vector layer.'))
        return layers

    def cut_all(self, dialog, layers, mask, target, context, feedback):
        """Cut every layer, keeping going after a failure: (completed pairs, failed names)."""
        completed, failed = [], []
        for index, layer in enumerate(layers):
            check_cancel(feedback)
            feedback.pushInfo(layer.name())
            try:
                completed.append((layer, cut_layer(layer, mask, target, context, feedback)))
            except Cancelled:
                raise
            except Exception as error:
                failed.append(layer.name())
                self.error(dialog, error)
            feedback.setProgress(100 * (index + 1) / len(layers))
        return completed, failed

    def mask_display_layer(self, dialog, mask, target, antipode, context, feedback):
        """The mask reprojected for display, or None: it is a convenience, not a result."""
        try:
            display = run('native:reprojectlayer', {'INPUT': mask, 'TARGET_CRS': target},
                          context, feedback)
            display.setName(tr('Antipodal mask') + ' ({:.3f}°)'.format(antipode))
            display.setRenderer(mask.renderer().clone())
            display.renderer().setSymbol(QgsFillSymbol.createSimple(MASK_FILL))
            return display
        except Cancelled:
            raise
        except Exception as error:
            feedback.pushInfo(tr('Could not display the mask: {0}').format(error))
            return None

    @staticmethod
    def hide_layers(project, layers):
        wanted = {layer.id() for layer in layers}
        for node in project.layerTreeRoot().findLayers():
            if node.layerId() in wanted:
                node.setItemVisibilityChecked(False)

    def execute_cutter(self, dialog):
        feedback = dialog.feedback
        try:
            project, context = self.context()
            target = project.crs()
            layers = self.chosen_layers(dialog, project)
            meridian = (dialog.meridian.value() if dialog.manual.isChecked()
                        else central_meridian(target))
            antipode = normalize_longitude(meridian + 180.0)
            feedback.pushInfo(tr('Central meridian: {0}°; antipodal meridian: {1}°.')
                              .format(meridian, antipode))
            mask = create_mask(antipode, dialog.width.value(), dialog.step.value())
            cutting = cutting_mask(mask, dialog.step.value())
            completed, failed = self.cut_all(dialog, layers, cutting, target, context, feedback)
            outputs = [output for _, output in completed]
            if completed and dialog.add_mask.isChecked():
                display = self.mask_display_layer(dialog, mask, target, antipode,
                                                  context, feedback)
                if display is not None:
                    outputs.append(display)
            check_cancel(feedback)
            if outputs:
                self.publish(outputs, project)
                if dialog.hide_originals.isChecked():
                    self.hide_layers(project, [original for original, _ in completed])
            feedback.pushInfo(tr('Completed: {0}; failed: {1}.')
                              .format(len(completed), len(failed)))
            if failed:
                feedback.pushInfo(tr('Failed layers: {0}').format(', '.join(failed)))
            if completed:
                feedback.pushInfo(
                    tr('Export temporary outputs to keep them after closing QGIS.'))
        except Cancelled:
            feedback.pushInfo(tr('Cancelled. No results from this run were added.'))
        except Exception as error:
            self.error(dialog, error)

    # --------------------------------------------------------------- outline tool

    def execute_outline(self, dialog):
        feedback = dialog.feedback
        try:
            project, context = self.context()
            line = dialog.output_type.currentIndex() == 0
            result = projection_outline(project.crs(), dialog.step.value(),
                                        dialog.edge.value(), line, context, feedback)
            symbol = (QgsLineSymbol.createSimple(OUTLINE_LINE) if line
                      else QgsFillSymbol.createSimple(OUTLINE_FILL))
            result.renderer().setSymbol(symbol)
            check_cancel(feedback)
            self.publish([result], project)
            feedback.pushInfo(tr('Export temporary outputs to keep them after closing QGIS.'))
        except Cancelled:
            feedback.pushInfo(tr('Cancelled. No results from this run were added.'))
        except Exception as error:
            self.error(dialog, error)
