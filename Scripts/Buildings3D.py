"""
Buildings3D - LoD2.2 building shells from 3DBAG for the LUX loader.

QGIS Processing script (algorithm id `script:buildings3d`). It takes the panden layer that the
Auto-GeoData models export as Buildings_, fetches the matching LoD2.2 shells from the 3DBAG API and
writes:

  * Buildings3D_<project>.xlsx/.csv  building_id, n_surfaces, n_vertices, polygon_3d
  * RoofSurfaces_<project>.xlsx/.csv (optional)  one row per roof plane, for the PV calculation
  * a MultiPolygonZ layer with the same shells, loaded into QGIS like the other model outputs

The columns and the WKT match lux2's demo data (demo/backend/data/*/Buildings3D_*.csv), which come from
lux2's tools/fetch-3dbag.mjs. This script is that tool's QGIS counterpart.

3DBAG API, CC BY 4.0, no key. Coordinates come in EPSG:7415 (RD New + NAP), and the API counts every
pand as two CityObjects (Building + BuildingPart), so paging follows the `next` link instead of counting.
"""

import csv
import json
import os
from urllib.parse import quote

from qgis.PyQt.QtCore import QMetaType, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    Qgis,
    QgsBlockingNetworkRequest,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsLineString,
    QgsMultiPolygon,
    QgsPolygon,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsRectangle,
    QgsWkbTypes,
)

API = 'https://api.3dbag.nl/collections/pand/items'
# Metres of slack around the input extent, so a pand on the boundary is not missed.
BBOX_PAD_M = 50
# Above this the area is fetched per pand instead: paging through a whole city takes longer than asking
# for the panden one by one.
MAX_BBOX_KM2 = 25
# CityObjects per page. Every pand is two of them, so this is about 100 panden.
PAGE = 200
# A surface must enclose at least this much area (m2) to be written.
MIN_AREA_M2 = 0.01
# A shell whose ground area differs more than this fraction from the input pand polygon is reported: 3DBAG
# lags behind BAG, so a new or rebuilt pand can come with an older, smaller or placeholder shell.
FOOTPRINT_TOLERANCE = 0.1
RETRIES = 3
# Excel keeps at most this many characters in a cell and cuts off the rest when it saves the file.
EXCEL_MAX_CELL = 32767
# Decimals for lon/lat. 8 matches the demo data (~1 mm); 7 and 6 (~1 cm, ~10 cm) are only used for a
# shell that would not fit in an Excel cell otherwise.
XY_DECIMALS = (8, 7, 6)

RD = QgsCoordinateReferenceSystem('EPSG:28992')
WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')


def normalize_id(value):
    """BAG pand id as 16 digits, from 'panduid.<id>', 'NL.IMBAG.Pand.<id>', a bare id or a number."""
    if value is None:
        return None
    text = str(value).strip()
    for prefix in ('panduid.', 'NL.IMBAG.Pand.'):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.endswith('.0'):
        text = text[:-2]
    if not text.isdigit():
        return None
    return text.zfill(16)


def ring_area(points):
    """Area of a planar 3D ring (Newell). Points must be in metres."""
    nx = ny = nz = 0.0
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return (nx * nx + ny * ny + nz * nz) ** 0.5 / 2


def convert(feature, transform):
    """One CityJSON feature -> its LoD2.2 surfaces in RD with heights above ground, and its roof planes."""
    objects = feature.get('CityObjects') or {}
    building_key = next((k for k, o in objects.items() if o.get('type') == 'Building'), None)
    if building_key is None:
        return None
    attributes = objects[building_key].get('attributes') or {}
    ground = attributes.get('b3_h_maaiveld')
    if ground is None:
        return None  # no datum to measure heights from; skip rather than guess

    scale, translate = transform['scale'], transform['translate']
    vertices = [
        (v[0] * scale[0] + translate[0],
         v[1] * scale[1] + translate[1],
         v[2] * scale[2] + translate[2] - ground)
        for v in feature.get('vertices') or []
    ]

    surfaces, roof_planes = [], []
    parts = [o for o in objects.values() if o.get('type') == 'BuildingPart'] or [objects[building_key]]
    for part in parts:
        geometry = next((g for g in part.get('geometry') or [] if str(g.get('lod')) == '2.2'), None)
        if not geometry or geometry.get('type') != 'Solid':
            continue
        semantics = geometry.get('semantics') or {}
        semantic_values = (semantics.get('values') or [[]])[0]
        semantic_surfaces = semantics.get('surfaces') or []
        for i, surface in enumerate(geometry['boundaries'][0]):
            rings = [[vertices[vi] for vi in ring] for ring in surface if len(ring) >= 3]
            if not rings or ring_area(rings[0]) < MIN_AREA_M2:
                continue
            surfaces.append(rings)

            index = semantic_values[i] if i < len(semantic_values) else None
            semantic = semantic_surfaces[index] if index is not None else None
            if not semantic or semantic.get('type') != 'RoofSurface':
                continue
            roof_height = semantic.get('b3_h_dak_50p')
            roof_planes.append({
                # The outer ring minus its holes: a roof measured without them is overstated.
                'area_m2': ring_area(rings[0]) - sum(ring_area(r) for r in rings[1:]),
                'azimuth_deg': semantic.get('b3_azimut'),
                'tilt_deg': semantic.get('b3_hellingshoek'),
                'height_m': None if roof_height is None else roof_height - ground,
            })
    if not surfaces:
        return None

    roof_max = attributes.get('b3_h_dak_max')
    return {
        'id': building_key.replace('NL.IMBAG.Pand.', ''),
        'surfaces': surfaces,
        'roof_planes': roof_planes,
        'height_m': None if roof_max is None else roof_max - ground,
        'footprint_m2': attributes.get('b3_opp_grond'),
        'valid': attributes.get('b3_val3dity_lod22') in (None, '[]'),
    }


def to_geometry(surfaces):
    """RD surfaces -> one MultiPolygonZ, one polygon per surface, holes as interior rings."""
    def ring(points):
        closed = points + points[:1]
        return QgsLineString([p[0] for p in closed], [p[1] for p in closed], [p[2] for p in closed])

    multipolygon = QgsMultiPolygon()
    for rings in surfaces:
        polygon = QgsPolygon()
        polygon.setExteriorRing(ring(rings[0]))
        for hole in rings[1:]:
            polygon.addInteriorRing(ring(hole))
        multipolygon.addGeometry(polygon)
    return QgsGeometry(multipolygon)


def to_wkt(geometry, xy_decimals):
    """`MULTIPOLYGON Z (((x y z, ...)), ...)` in the exact layout of lux2's demo data."""
    def ring(line):
        # round() + 0.0 turns a ground vertex a hair below zero into 0.00 rather than -0.00.
        return '(' + ', '.join(
            f'{p.x():.{xy_decimals}f} {p.y():.{xy_decimals}f} {round(p.z(), 2) + 0.0:.2f}'
            for p in line.points()) + ')'

    polygons = []
    for polygon in geometry.constParts():
        rings = [polygon.exteriorRing()] + [polygon.interiorRing(i) for i in range(polygon.numInteriorRings())]
        polygons.append('(' + ', '.join(ring(r) for r in rings) + ')')
    return 'MULTIPOLYGON Z (' + ', '.join(polygons) + ')'


def write_table(path, sheet_name, header, rows):
    """Write rows to .xlsx (one sheet) or .csv, chosen by the file extension."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if path.lower().endswith('.csv'):
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(header)
            # Measurements are rounded to cm; written as 7.80 rather than 7.8, like the demo data.
            writer.writerows([f'{v:.2f}' if isinstance(v, float) else v for v in row] for row in rows)
        return
    try:
        from openpyxl import Workbook
    except ImportError:
        raise QgsProcessingException('openpyxl is not available in this QGIS Python; save as .csv instead.')
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(sheet_name)
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


class Buildings3DAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    ID_FIELD = 'ID_FIELD'
    OUTPUT = 'OUTPUT'
    BUILDINGS3D = 'BUILDINGS3D'
    ROOFSURFACES = 'ROOFSURFACES'

    def name(self):
        return 'buildings3d'

    def displayName(self):
        return 'Buildings3D (3DBAG LoD2.2)'

    def group(self):
        return 'LUX'

    def groupId(self):
        return 'lux'

    def shortHelpString(self):
        return (
            'Fetches the LoD2.2 shells of the input panden from 3DBAG (api.3dbag.nl) and writes '
            'Buildings3D_ for the LUX loader: building_id, n_surfaces, n_vertices and polygon_3d as '
            'MULTIPOLYGON Z in WGS84, with heights in metres above ground level.\n\n'
            'Input: the panden layer that is exported as Buildings_ (one row per address is fine). '
            'The id field may hold "panduid.<id>", "NL.IMBAG.Pand.<id>" or the bare BAG id.\n\n'
            'Save as .xlsx or .csv; the loader reads both. Excel holds at most 32,767 characters per '
            'cell, so in .xlsx a very large shell is written with fewer decimals (reported in the log).\n\n'
            'RoofSurfaces_ holds one row per roof plane: area, azimuth, tilt and height. It can be '
            'skipped when run on its own; the Auto-GeoData models always write it.\n\n'
            '3DBAG lags behind BAG. Panden it does not have yet get no shell, and the layer\'s '
            'footprint_ratio (3DBAG ground area / input polygon area) shows where it holds an older '
            'version of a pand. Both are listed in the log.\n\n'
            'Source: 3DBAG by the 3D geoinformation group, TU Delft (CC BY 4.0).'
        )

    def createInstance(self):
        return Buildings3DAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, 'Panden', [Qgis.ProcessingSourceType.Vector]))
        self.addParameter(QgsProcessingParameterField(
            self.ID_FIELD, 'Building ID field', defaultValue='building_id', parentLayerParameterName=self.INPUT))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Buildings3D', Qgis.ProcessingSourceType.VectorPolygon))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.BUILDINGS3D, 'Buildings3D_', 'Microsoft Excel (*.xlsx);;CSV (*.csv)'))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.ROOFSURFACES, 'RoofSurfaces_', 'Microsoft Excel (*.xlsx);;CSV (*.csv)', optional=True))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        id_field = self.parameterAsString(parameters, self.ID_FIELD, context)
        buildings3d_path = self.parameterAsFileOutput(parameters, self.BUILDINGS3D, context)
        roofsurfaces_path = self.parameterAsFileOutput(parameters, self.ROOFSURFACES, context)

        ids, located, areas, bbox = self.scope(source, id_field, context)
        if not ids:
            raise QgsProcessingException(f'No BAG pand ids found in field "{id_field}".')
        feedback.pushInfo(f'{len(ids)} panden in the input')

        buildings = {}
        covered = set()
        seen = 0
        if bbox is not None and bbox.area() <= MAX_BBOX_KM2 * 1e6:
            covered = located
            feedback.pushInfo('Fetching 3DBAG for RD bbox ' + ', '.join(
                str(round(v)) for v in (bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum())))
            for features, transform in self.fetch_area(bbox, feedback):
                for feature in features:
                    seen += 1
                    building = convert(feature, transform)
                    if building and building['id'] in ids:
                        buildings.setdefault(building['id'], building)
            feedback.pushInfo(f'{seen} buildings in the area, {len(buildings)} of them in the input')

        # Panden the area did not cover (no geometry in the input, or an area too large to page through) are
        # asked for one by one. A pand inside the area that 3DBAG did not return is not in 3DBAG.
        by_id = sorted(ids - buildings.keys() - covered)
        if by_id:
            feedback.pushInfo(f'Fetching {len(by_id)} panden by id')
        for n, pand_id in enumerate(by_id):
            if feedback.isCanceled():
                break
            feedback.setProgress(100 * n / len(by_id))
            body = self.get_json(f'{API}/{quote("NL.IMBAG.Pand." + pand_id)}', feedback, allow_missing=True)
            if body and body.get('feature'):
                building = convert(body['feature'], body['metadata']['transform'])
                if building:
                    buildings[pand_id] = building
        if feedback.isCanceled():
            return {}  # write nothing rather than a file that silently lacks panden
        missing = sorted(ids - buildings.keys())

        to_wgs84 = QgsCoordinateTransform(RD, WGS84, context.transformContext())
        fields = QgsFields()
        fields.append(QgsField('building_id', QMetaType.Type.QString))
        fields.append(QgsField('n_surfaces', QMetaType.Type.Int))
        fields.append(QgsField('n_vertices', QMetaType.Type.Int))
        fields.append(QgsField('height_m', QMetaType.Type.Double))
        fields.append(QgsField('footprint_ratio', QMetaType.Type.Double))
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, Qgis.WkbType.MultiPolygonZ, WGS84)
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        to_excel = not buildings3d_path.lower().endswith('.csv')
        shell_rows, roof_rows, coarser, too_long, mismatched = [], [], [], [], []
        for pand_id in sorted(buildings):
            building = buildings[pand_id]
            # 3DBAG ground area over the input polygon's; only known when the input has polygons.
            ratio = None
            if building['footprint_m2'] is not None and areas.get(pand_id):
                ratio = building['footprint_m2'] / areas[pand_id]
                if abs(ratio - 1) > FOOTPRINT_TOLERANCE:
                    mismatched.append(f'{pand_id} ({ratio:.2f})')
            geometry = to_geometry(building['surfaces'])
            geometry.transform(to_wgs84)
            # Vertices without the closing repeat, as in the demo data.
            n_vertices = sum(len(ring) for rings in building['surfaces'] for ring in rings)

            wkt = to_wkt(geometry, XY_DECIMALS[0])
            if to_excel:
                for decimals in XY_DECIMALS[1:]:
                    if len(wkt) <= EXCEL_MAX_CELL:
                        break
                    wkt = to_wkt(geometry, decimals)
                    coarser.append(f'{pand_id} ({decimals} decimals)')
                if len(wkt) > EXCEL_MAX_CELL:
                    too_long.append(pand_id)
            shell_rows.append([pand_id, len(building['surfaces']), n_vertices, wkt])

            for index, plane in enumerate(building['roof_planes']):
                roof_rows.append([pand_id, index] + [
                    None if plane[k] is None else round(plane[k], 2)
                    for k in ('area_m2', 'azimuth_deg', 'tilt_deg', 'height_m')])

            feature = QgsFeature(fields)
            feature.setGeometry(geometry)
            feature.setAttributes([
                pand_id, len(building['surfaces']), n_vertices,
                None if building['height_m'] is None else round(building['height_m'], 2),
                None if ratio is None else round(ratio, 2)])
            sink.addFeature(feature, QgsFeatureSink.Flag.FastInsert)

        write_table(buildings3d_path, 'buildings3d', ['building_id', 'n_surfaces', 'n_vertices', 'polygon_3d'],
                    shell_rows)
        if roofsurfaces_path:
            write_table(roofsurfaces_path, 'roofsurfaces',
                        ['building_id', 'plane_index', 'area_m2', 'azimuth_deg', 'tilt_deg', 'height_m'], roof_rows)

        feedback.pushInfo(f'Buildings3D: {len(shell_rows)} of {len(ids)} panden, '
                          f'{sum(r[1] for r in shell_rows)} surfaces, {len(roof_rows)} roof planes')
        invalid = sorted(b['id'] for b in buildings.values() if not b['valid'])
        if invalid:
            feedback.pushWarning(f'{len(invalid)} shells carry a 3DBAG validity error (b3_val3dity_lod22): '
                                 + ', '.join(invalid))
        if missing:
            feedback.pushWarning(f'{len(missing)} panden not in 3DBAG (often built after its latest AHN '
                                 'point cloud), so without a 3D shell: ' + ', '.join(missing))
        if mismatched:
            feedback.pushWarning(f'{len(mismatched)} shells differ more than {FOOTPRINT_TOLERANCE:.0%} in ground '
                                 'area from the input pand (3DBAG holds an older version of it); see '
                                 'footprint_ratio in the Buildings3D layer: ' + ', '.join(mismatched))
        if coarser:
            feedback.pushWarning('Written with fewer decimals to fit an Excel cell: ' + ', '.join(coarser))
        if too_long:
            feedback.pushWarning('Still longer than an Excel cell holds; LUX reads them, but Excel cuts them '
                                 'off when the file is saved again. Save as .csv to avoid that: '
                                 + ', '.join(too_long))

        return {self.OUTPUT: dest_id, self.BUILDINGS3D: buildings3d_path, self.ROOFSURFACES: roofsurfaces_path}

    @staticmethod
    def scope(source, id_field, context):
        """The input's pand ids, the ids that have a geometry, their polygon areas in m2 (polygon input
        only) and their extent as a padded RD rectangle (None without geometries)."""
        if source.fields().lookupField(id_field) < 0:
            raise QgsProcessingException(f'Field "{id_field}" is not in the input layer.')
        to_rd = None
        if source.sourceCrs().isValid():
            to_rd = QgsCoordinateTransform(source.sourceCrs(), RD, context.transformContext())
        polygons = QgsWkbTypes.geometryType(source.wkbType()) == Qgis.GeometryType.Polygon
        ids, located, areas = set(), set(), {}
        extent = QgsRectangle()
        extent.setNull()
        for feature in source.getFeatures():
            pand_id = normalize_id(feature[id_field])
            if not pand_id:
                continue
            ids.add(pand_id)
            if to_rd is None or not feature.hasGeometry():
                continue
            located.add(pand_id)
            geometry = QgsGeometry(feature.geometry())
            geometry.transform(to_rd)
            extent.combineExtentWith(geometry.boundingBox())
            if polygons:
                areas.setdefault(pand_id, geometry.area())  # one row per address: same pand, same polygon
        if extent.isNull():
            return ids, located, areas, None
        extent.grow(BBOX_PAD_M)
        return ids, located, areas, extent

    def fetch_area(self, bbox, feedback):
        """Yield (features, transform) per page. The transform is per response, shared by its features."""
        url = (f'{API}?bbox={bbox.xMinimum():.2f},{bbox.yMinimum():.2f},{bbox.xMaximum():.2f},'
               f'{bbox.yMaximum():.2f}&limit={PAGE}')
        returned = 0
        while url:
            if feedback.isCanceled():
                return
            body = self.get_json(url, feedback)
            returned += body.get('numberReturned') or 0
            if body.get('numberMatched'):
                feedback.setProgress(100 * returned / body['numberMatched'])
            yield body.get('features') or [], body['metadata']['transform']
            # Follow the link; an offset computed from a feature count skips half the panden.
            url = next((link['href'] for link in body.get('links') or [] if link.get('rel') == 'next'), None)

    @staticmethod
    def get_json(url, feedback, allow_missing=False):
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b'Accept', b'application/json')
        error = ''
        for _ in range(RETRIES):
            blocking = QgsBlockingNetworkRequest()
            if blocking.get(request, True, feedback) == QgsBlockingNetworkRequest.ErrorCode.NoError:
                return json.loads(bytes(blocking.reply().content()).decode('utf-8'))
            if feedback.isCanceled():
                raise QgsProcessingException('Canceled')
            status = blocking.reply().attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            # 3DBAG answers an unknown pand id with 502 Bad Gateway rather than 404.
            if allow_missing and status in (404, 502):
                return None
            error = blocking.errorMessage()
            feedback.pushWarning(f'3DBAG request failed, retrying: {error}')
        raise QgsProcessingException(f'3DBAG request failed after {RETRIES} attempts: {url}\n{error}')
