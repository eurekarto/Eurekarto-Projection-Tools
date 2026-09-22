"""Tests for eurekarto_projection_tools, run without QGIS.

QGIS cannot be imported here, so the qgis package and the processing module are
replaced by the smallest stand-ins the code actually touches. That covers the
pure logic: longitude normalisation, central meridian detection, the antipodal
band and its wrap at ±180°, mask latitudes, and cell rejection. Anything that
needs QGIS — reprojection, native algorithms, dialogs — must be tested in QGIS.

Run: python3 test_projection_tools.py
"""
import pathlib
import sys
import types
import math
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
                 'QgsVectorLayer', 'QgsRectangle'):
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
from eurekarto_projection_tools import horizon  # noqa: E402
from eurekarto_projection_tools import seams  # noqa: E402
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
    """The displayed mask stops short of the poles; the caps are cut separately."""

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

    def test_the_displayed_mask_stops_a_tenth_of_a_degree_from_each_pole(self):
        self.assertAlmostEqual(90.0 - antimeridian.POLAR_LIMIT, 0.1, 9)


class PolarCaps(unittest.TestCase):
    """Both caps beyond the polar limit are cut away with the band."""

    def test_the_caps_run_from_the_limit_to_the_poles(self):
        self.assertEqual(antimeridian.polar_caps(),
                         [(-90.0, -antimeridian.POLAR_LIMIT), (antimeridian.POLAR_LIMIT, 90.0)])

    def test_a_cap_ring_is_closed_and_spans_every_longitude(self):
        ring = antimeridian.cap_ring(-90.0, -antimeridian.POLAR_LIMIT, 0.5)
        self.assertEqual(ring[0], ring[-1])
        longitudes = [x for x, _ in ring]
        self.assertEqual((min(longitudes), max(longitudes)), (-180.0, 180.0))

    def test_a_cap_ring_carries_a_vertex_at_least_every_step(self):
        ring = antimeridian.cap_ring(-90.0, -antimeridian.POLAR_LIMIT, 0.7)
        north_edge = [x for x, y in ring[:len(ring) // 2]]
        gaps = [second - first for first, second in zip(north_edge, north_edge[1:])]
        self.assertLessEqual(max(gaps), 0.7 + 1e-9)

    def test_band_and_caps_leave_no_gap_between_them(self):
        # The band spans -POLAR_LIMIT..POLAR_LIMIT; the caps must start exactly there.
        south, north = antimeridian.polar_caps()
        self.assertEqual(south[1], -antimeridian.POLAR_LIMIT)
        self.assertEqual(north[0], antimeridian.POLAR_LIMIT)


try:
    from pyproj import Transformer
    from shapely.geometry import Point as ShapelyPoint, Polygon, box
    from shapely.ops import transform, unary_union
    GEOMETRY_LIBRARIES = True
except ImportError:
    GEOMETRY_LIBRARIES = False


@unittest.skipUnless(GEOMETRY_LIBRARIES, 'needs shapely and pyproj')
class ConicProjection(unittest.TestCase):
    """The reported case, replayed with PROJ: Antarctica in a conic centred on Europe.

    The geometry is reprojected vertex by vertex and never densified on the way,
    exactly as QGIS's reprojection does: an earlier version of this test densified
    it first, and so passed while the plugin still failed.
    """

    central = 10.0

    def cut(self, caps):
        antipode = antimeridian.normalize_longitude(self.central + 180.0)
        limit = antimeridian.POLAR_LIMIT
        parts = [box(left, -limit, right, limit)
                 for left, right in antimeridian.mask_intervals(antipode, 0.1)]
        parts += caps
        longitudes = [-180.0 + index for index in range(361)]
        antarctica = Polygon([(x, -65.0) for x in longitudes]
                             + [(x, -90.0) for x in reversed(longitudes)])
        return antarctica.difference(unary_union(parts))

    def covers_paris(self, geometry):
        to_map = Transformer.from_crs(
            'EPSG:4326', '+proj=lcc +lat_1=35 +lat_2=65 +lat_0=52 +lon_0={0} '
            '+datum=WGS84'.format(self.central), always_xy=True).transform
        projected = transform(to_map, geometry).buffer(0)
        return projected.contains(transform(to_map, ShapelyPoint(2.35, 48.85)))

    def test_the_band_alone_leaves_antarctica_covering_europe(self):
        self.assertTrue(self.covers_paris(self.cut([])))

    def test_caps_with_four_corners_still_cover_europe(self):
        # The 1.0.3 defect: an edge of 360 degrees carried by two vertices becomes
        # a straight chord once projected.
        caps = [box(-180.0, south, 180.0, north) for south, north in antimeridian.polar_caps()]
        self.assertTrue(self.covers_paris(self.cut(caps)))

    def test_the_plugin_densified_caps_free_europe(self):
        caps = [Polygon(antimeridian.cap_ring(south, north, 0.5))
                for south, north in antimeridian.polar_caps()]
        self.assertFalse(self.covers_paris(self.cut(caps)))


class Styles(unittest.TestCase):
    """Every cut must hand back a layer that looks like the one it came from."""

    class Source:
        def __init__(self, renderer=None, labeling=None, labels=True):
            self._renderer, self._labeling, self._labels = renderer, labeling, labels

        def renderer(self):
            return self._renderer

        def labeling(self):
            return self._labeling

        def labelsEnabled(self):
            return self._labels

    class Result:
        def __init__(self):
            self.renderer_set = self.labeling_set = self.labels_set = None

        def setRenderer(self, renderer):
            self.renderer_set = renderer

        def setLabeling(self, labeling):
            self.labeling_set = labeling

        def setLabelsEnabled(self, enabled):
            self.labels_set = enabled

    @staticmethod
    def clonable(name):
        clone = types.SimpleNamespace(name=name)
        return types.SimpleNamespace(clone=lambda: clone), clone

    def test_the_symbology_is_carried_over(self):
        renderer, clone = self.clonable('symbology')
        result = self.Result()
        common.carry_style(self.Source(renderer=renderer), result)
        self.assertIs(result.renderer_set, clone)

    def test_the_labelling_is_carried_over(self):
        labeling, clone = self.clonable('labels')
        result = self.Result()
        common.carry_style(self.Source(labeling=labeling, labels=True), result)
        self.assertIs(result.labeling_set, clone)
        self.assertTrue(result.labels_set)

    def test_a_layer_without_a_style_is_left_alone(self):
        result = self.Result()
        common.carry_style(self.Source(), result)
        self.assertIsNone(result.renderer_set)
        self.assertIsNone(result.labeling_set)

    def test_every_cut_carries_the_style(self):
        """The three cutting paths must all end on carry_style, not just the first."""
        folder = pathlib.Path('eurekarto_projection_tools')
        sources = [(folder / name).read_text(encoding='utf-8')
                   for name in ('antimeridian.py', 'masks.py')]
        for text in sources:
            for block in text.split('def ')[1:]:
                if "setName(layer.name() + ' Projection Tool')" in block:
                    self.assertIn('carry_style', block)


class Horizon(unittest.TestCase):
    """The cap a projection can show, built from the centre and the radius alone."""

    def test_a_point_at_zero_distance_is_the_centre(self):
        latitude, longitude = horizon.point_at(48.0, 2.0, 0.0, 0.0)
        self.assertAlmostEqual(latitude, 48.0, 9)
        self.assertAlmostEqual(longitude, 2.0, 9)

    def test_a_point_due_north_gains_latitude(self):
        latitude, longitude = horizon.point_at(0.0, 0.0, 30.0, 0.0)
        self.assertAlmostEqual(latitude, 30.0, 6)
        self.assertAlmostEqual(longitude, 0.0, 6)

    def test_a_point_due_east_of_the_equator_gains_longitude(self):
        latitude, longitude = horizon.point_at(0.0, 10.0, 30.0, 90.0)
        self.assertAlmostEqual(latitude, 0.0, 6)
        self.assertAlmostEqual(longitude, 40.0, 6)

    def test_a_cap_away_from_the_poles_is_one_ring(self):
        self.assertEqual(len(horizon.cap_rings(20.0, 30.0, 40.0)), 1)

    def test_a_cap_over_the_date_line_is_split_in_two(self):
        self.assertEqual(len(horizon.cap_rings(-33.0, 151.0, 30.0)), 2)

    def test_a_cap_holding_a_pole_is_closed_along_the_map_edge(self):
        ring = horizon.cap_rings(90.0, 0.0, 90.0)[0]
        longitudes = [longitude for longitude, _ in ring]
        self.assertEqual((min(longitudes), max(longitudes)), (-180.0, 180.0))
        self.assertIn(90.0, [latitude for _, latitude in ring])

    def test_the_radius_stays_inside_the_horizon(self):
        # Exactly on the horizon a projection often refuses the point.
        ring = horizon.cap_rings(0.0, 0.0, 90.0)[0]
        self.assertLess(max(abs(longitude) for longitude, _ in ring), 90.0)

    def test_the_centre_is_read_from_the_projection(self):
        self.assertEqual(horizon.centre_from_proj('+proj=ortho +lat_0=20 +lon_0=30 +R=6371000'),
                         (20.0, 30.0))
        self.assertEqual(horizon.centre_from_proj('+proj=ortho'), (0.0, 0.0))
        self.assertEqual(horizon.centre_from_proj('+proj=ortho +lon_0=200'), (0.0, -160.0))


class Seams(unittest.TestCase):
    """Finding the tears by projecting a grid, with no aspect assumed."""

    def test_a_cell_with_an_unplaceable_corner_has_no_length(self):
        self.assertIsNone(seams.longest_side([(0, 0), None, (1, 1), (0, 1)]))

    def test_the_longest_side_is_measured_round_the_cell(self):
        self.assertAlmostEqual(seams.longest_side([(0, 0), (3, 0), (3, 1), (0, 1)]), 3.0, 9)

    def test_a_column_straddles_the_date_line(self):
        cells, columns, rows = seams.cell_bounds(2.0)
        self.assertTrue(any(west < 180.0 < east for west, east, _, _ in cells))
        self.assertEqual(columns, 181)

    def test_a_cell_crossing_the_date_line_is_split_for_the_mask(self):
        self.assertEqual(seams.split_at_date_line(179.0, 181.0),
                         [(179.0, 180.0), (-180.0, -179.0)])
        self.assertEqual(seams.split_at_date_line(10.0, 12.0), [(10.0, 12.0)])

    def test_the_second_grid_is_shifted_by_half_a_cell(self):
        # A tear sitting on the lines of one grid must fall inside a cell of the other.
        first, _, _ = seams.cell_bounds(2.0, 0.0)
        second, _, _ = seams.cell_bounds(2.0, 1.0)
        self.assertIn(-170.0, [west for west, _, _, _ in first])
        self.assertNotIn(-170.0, [west for west, _, _, _ in second])


@unittest.skipUnless(GEOMETRY_LIBRARIES, 'needs shapely and pyproj')
class SeamsWithProj(unittest.TestCase):
    """The detector measured against real projections."""

    @staticmethod
    def projector(definition):
        import math as arithmetic
        transformer = Transformer.from_crs('EPSG:4326', definition, always_xy=True)

        def project(points):
            xs, ys = transformer.transform([p[0] for p in points], [p[1] for p in points])
            return [(x, y) if arithmetic.isfinite(x) and arithmetic.isfinite(y) else None
                    for x, y in zip(xs, ys)]

        return project

    def found(self, definition, step=2.0):
        return seams.torn_cells(self.projector(definition), step=step)

    def test_a_world_projection_tears_along_its_antipodal_meridian(self):
        cells = self.found('+proj=robin +lon_0=-90 +datum=WGS84')
        longitudes = {round((west + east) / 2) for west, east, _, _ in cells}
        self.assertTrue(longitudes <= {90, 91}, longitudes)

    def test_cassini_tears_along_the_far_half_of_the_equator(self):
        cells = self.found('ESRI:53028')
        latitudes = {round((south + north) / 2) for _, _, south, north in cells}
        self.assertTrue(latitudes <= {-1, 0, 1}, latitudes)
        # Nothing is cut within 90° of the central meridian.
        near = [west for west, east, _, _ in cells if abs((west + east) / 2) < 88]
        self.assertEqual(near, [])

    def test_a_conic_keeps_its_stretched_hemisphere(self):
        # A stretch is not a tear: at most a few percent of the globe may be cut.
        cells = self.found('+proj=lcc +lat_1=35 +lat_2=65 +lon_0=10 +datum=WGS84')
        self.assertLess(len(cells), 0.05 * 181 * 90 * 2)

    def test_an_azimuthal_equidistant_has_nothing_to_cut(self):
        self.assertEqual(self.found('+proj=aeqd +lat_0=48 +lon_0=2 +datum=WGS84'), [])

    def test_an_orthographic_hides_half_the_globe(self):
        cells = self.found('+proj=ortho +lat_0=20 +lon_0=30 +R=6371000')
        share = len(cells) / (181 * 90 * 2)
        self.assertGreater(share, 0.4)


@unittest.skipUnless(GEOMETRY_LIBRARIES, 'needs shapely and pyproj')
class HorizonArea(unittest.TestCase):
    """The cap must cover the share of the globe its radius implies."""

    @staticmethod
    def share(latitude, longitude, radius):
        rings = horizon.cap_rings(latitude, longitude, radius, step=1.0)
        shape = unary_union([Polygon(ring).buffer(0) for ring in rings])
        import random
        generator = random.Random(3)
        inside = 0
        for _ in range(4000):
            sample_latitude = math.degrees(math.asin(generator.uniform(-1, 1)))
            sample_longitude = generator.uniform(-180, 180)
            if shape.contains(ShapelyPoint(sample_longitude, sample_latitude)):
                inside += 1
        return inside / 4000

    def expected(self, radius):
        return (1 - math.cos(math.radians(radius))) / 2

    def test_a_hemisphere_covers_half_the_globe(self):
        for latitude, longitude in ((0.0, 0.0), (20.0, 30.0), (90.0, 0.0), (0.0, 180.0)):
            self.assertAlmostEqual(self.share(latitude, longitude, 90.0),
                                   self.expected(90.0), delta=0.02)

    def test_a_smaller_cap_covers_its_share(self):
        self.assertAlmostEqual(self.share(48.0, 2.0, 60.0), self.expected(60.0), delta=0.02)

    def test_a_cap_larger_than_a_hemisphere_covers_its_share(self):
        self.assertAlmostEqual(self.share(70.0, -40.0, 120.0), self.expected(120.0), delta=0.02)


if __name__ == '__main__':
    unittest.main(verbosity=2)
