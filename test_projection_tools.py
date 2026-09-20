"""Tests for eurekarto_projection_tools, run without QGIS.

QGIS cannot be imported here, so the qgis package and the processing module are
replaced by the smallest stand-ins the code actually touches. That covers the
pure logic: longitude normalisation, central meridian detection, the antipodal
band and its wrap at ±180°, mask latitudes, and cell rejection. Anything that
needs QGIS — reprojection, native algorithms, dialogs — must be tested in QGIS.

Run: python3 test_projection_tools.py
"""
import math
import pathlib
import sys
import types
import unittest


class Point:
    def __init__(self, x, y):
        self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class Crs:
    """Just enough of QgsCoordinateReferenceSystem for meridian detection."""

    def __init__(self, proj, geographic=False, valid=True):
        self._proj, self._geographic, self._valid = proj, geographic, valid

    def toProj(self):
        return self._proj

    def isGeographic(self):
        return self._geographic

    def isValid(self):
        return self._valid


def install_stubs():
    qgis = types.ModuleType('qgis')
    qgis.__path__ = []
    core = types.ModuleType('qgis.core')
    pyqt = types.ModuleType('qgis.PyQt')
    pyqt.__path__ = []
    qtcore = types.ModuleType('qgis.PyQt.QtCore')
    qtcore.QCoreApplication = types.SimpleNamespace(translate=lambda context, text: text)

    class QgsProcessingException(Exception):
        pass

    core.QgsProcessingException = QgsProcessingException
    core.Qgis = types.SimpleNamespace(
        GeometryType=types.SimpleNamespace(Line='line', Polygon='polygon', Point='point'))
    core.QgsPointXY = Point
    core.QgsCsException = type('QgsCsException', (Exception,), {})

    class QgsGeometry:
        """Records the ring it was built from; area and validity from the ring."""

        def __init__(self, ring):
            self.ring = ring

        @staticmethod
        def fromPolygonXY(rings):
            return QgsGeometry(rings[0])

        def isEmpty(self):
            return len(self.ring) < 4

        def isGeosValid(self):
            return True

        def area(self):
            total = 0.0
            for index in range(len(self.ring) - 1):
                first, second = self.ring[index], self.ring[index + 1]
                total += first.x() * second.y() - second.x() * first.y()
            return abs(total) / 2.0

    core.QgsGeometry = QgsGeometry
    for name in ('QgsCoordinateReferenceSystem', 'QgsCoordinateTransform', 'QgsFeature',
                 'QgsVectorLayer'):
        setattr(core, name, type(name, (object,), {}))

    qgis.core = core
    qgis.PyQt = pyqt
    pyqt.QtCore = qtcore
    sys.modules.update({'qgis': qgis, 'qgis.core': core, 'qgis.PyQt': pyqt,
                        'qgis.PyQt.QtCore': qtcore,
                        'processing': types.ModuleType('processing')})

    package = types.ModuleType('eurekarto_projection_tools')
    package.__path__ = [str(pathlib.Path(__file__).resolve().parent
                            / 'eurekarto_projection_tools')]
    sys.modules['eurekarto_projection_tools'] = package
    return QgsProcessingException


ProcessingError = install_stubs()
from eurekarto_projection_tools import antimeridian  # noqa: E402
from eurekarto_projection_tools import common  # noqa: E402
from eurekarto_projection_tools import outline  # noqa: E402


class Longitudes(unittest.TestCase):
    def test_wraps_into_the_conventional_domain(self):
        for value, expected in ((0, 0), (181, -179), (-190, 170), (360, 0), (540, -180)):
            self.assertAlmostEqual(antimeridian.normalize_longitude(value), expected, 9)

    def test_sends_both_signed_forms_of_the_date_line_to_the_same_value(self):
        self.assertEqual(antimeridian.normalize_longitude(180.0),
                         antimeridian.normalize_longitude(-180.0))


class CentralMeridian(unittest.TestCase):
    def test_reads_the_projection_parameter(self):
        self.assertAlmostEqual(
            antimeridian.central_meridian(Crs('+proj=eqearth +lon_0=-92.5 +datum=WGS84')),
            -92.5, 9)

    def test_derives_the_meridian_of_a_utm_zone(self):
        for zone, expected in ((1, -177.0), (31, 3.0), (60, 177.0)):
            crs = Crs('+proj=utm +zone={0} +datum=WGS84'.format(zone))
            self.assertAlmostEqual(antimeridian.central_meridian(crs), expected, 9)

    def test_a_geographic_crs_is_centred_on_greenwich(self):
        self.assertEqual(antimeridian.central_meridian(Crs('+proj=longlat', geographic=True)),
                         0.0)

    def test_refuses_a_shifted_prime_meridian_rather_than_guessing(self):
        with self.assertRaises(ProcessingError):
            antimeridian.central_meridian(Crs('+proj=tmerc +lon_0=0 +pm=paris'))

    def test_refuses_a_projection_it_cannot_read(self):
        with self.assertRaises(ProcessingError):
            antimeridian.central_meridian(Crs('+proj=laea +lat_0=45'))

    def test_normalises_an_out_of_range_parameter(self):
        self.assertAlmostEqual(
            antimeridian.central_meridian(Crs('+proj=merc +lon_0=200')), -160.0, 9)


class MaskIntervals(unittest.TestCase):
    def width(self, intervals):
        return sum(right - left for left, right in intervals)

    def test_a_band_away_from_the_date_line_stays_in_one_piece(self):
        self.assertEqual(antimeridian.mask_intervals(0.0, 0.1), [(-0.1, 0.1)])

    def test_a_band_over_the_date_line_is_split_in_two(self):
        intervals = antimeridian.mask_intervals(180.0, 0.1)
        self.assertEqual(len(intervals), 2)
        self.assertAlmostEqual(self.width(intervals), 0.2, 9)

    def test_both_wrap_directions_keep_the_full_width(self):
        for antipode in (179.95, -179.95, 180.0, -180.0):
            self.assertAlmostEqual(
                self.width(antimeridian.mask_intervals(antipode, 0.1)), 0.2, 9)

    def test_every_interval_stays_inside_the_domain(self):
        for antipode in (179.95, -179.95, 0.0, 90.0):
            for left, right in antimeridian.mask_intervals(antipode, 0.1):
                self.assertGreaterEqual(left, -180.0)
                self.assertLessEqual(right, 180.0)
                self.assertLess(left, right)

    def test_refuses_a_width_outside_its_range(self):
        with self.assertRaises(ProcessingError):
            antimeridian.mask_intervals(0.0, 25.0)


class Bounds(unittest.TestCase):
    def test_accepts_a_value_inside_the_range(self):
        common.bounded(1.0, 0.0, 2.0)

    def test_refuses_a_value_outside_the_range(self):
        with self.assertRaises(ProcessingError):
            common.bounded(3.0, 0.0, 2.0)

    def test_refuses_a_value_that_is_not_a_number(self):
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ProcessingError):
                common.bounded(value, 0.0, 2.0)


class GridCells(unittest.TestCase):
    square = [Point(0, 0), Point(1, 0), Point(1, 1), Point(0, 1)]

    def test_keeps_a_well_formed_cell(self):
        self.assertIsNotNone(outline.cell_geometry(self.square, 10.0))

    def test_rejects_a_cell_with_a_corner_the_projection_cannot_place(self):
        self.assertIsNone(outline.cell_geometry([Point(0, 0), None, Point(1, 1), Point(0, 1)],
                                                10.0))

    def test_rejects_a_cell_stretched_across_an_interruption(self):
        stretched = [Point(0, 0), Point(5000, 0), Point(5000, 1), Point(0, 1)]
        self.assertIsNone(outline.cell_geometry(stretched, 10.0))

    def test_rejects_a_collapsed_cell(self):
        flat = [Point(0, 0), Point(1, 0), Point(1, 0), Point(0, 0)]
        self.assertIsNone(outline.cell_geometry(flat, 10.0))

    def test_measures_the_closing_edge_too(self):
        # The last corner returns far from the first: only a closed-ring test sees it.
        open_ring = [Point(0, 0), Point(1, 0), Point(1, 1), Point(0, 5000)]
        self.assertIsNone(outline.cell_geometry(open_ring, 10.0))


class MaskLatitudes(unittest.TestCase):
    """The mask stops short of the poles; the residue must stay what it claims."""

    def latitudes(self, step):
        span = 2 * antimeridian.POLAR_LIMIT
        count = math.ceil(span / step)
        return [-antimeridian.POLAR_LIMIT + min(index * step, span)
                for index in range(count + 1)]

    def test_spans_from_one_limit_to_the_other(self):
        for step in (0.5, 0.7, 1.0, 3.0):
            latitudes = self.latitudes(step)
            self.assertAlmostEqual(latitudes[0], -antimeridian.POLAR_LIMIT, 9)
            self.assertAlmostEqual(latitudes[-1], antimeridian.POLAR_LIMIT, 9)

    def test_never_repeats_its_last_vertex(self):
        for step in (0.5, 0.7, 1.3, 7.0):
            latitudes = self.latitudes(step)
            self.assertNotEqual(latitudes[-1], latitudes[-2])

    def test_the_uncut_polar_residue_is_a_tenth_of_a_degree(self):
        self.assertAlmostEqual(90.0 - antimeridian.POLAR_LIMIT, 0.1, 9)


if __name__ == '__main__':
    unittest.main(verbosity=2)
