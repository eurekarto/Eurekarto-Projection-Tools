# Eurekarto Projection Tools — 1.0.4

© 2026 Blanche Lambert / Eurêkarto  
Created by Blanche Lambert for Eurêkarto in 2026.  
License: GNU GPL v2 or later (`GPL-2.0-or-later`).  
Contact: contact@eurekarto.com  
Source and issues: https://github.com/eurekarto/Eurekarto-Projection-Tools

## Installation / Installation

**Français** — Dans QGIS 3.40 LTR ou QGIS 4 : **Extensions → Installer/Gérer les extensions → Installer depuis un ZIP**. Sélectionnez `eurekarto_projection_tools-1_0_4.zip`, puis activez l’extension. Les deux outils apparaissent dans le menu **Extensions → Eurekarto Projection Tools** et dans la barre d’outils des extensions. Aucun paquet Python supplémentaire n’est nécessaire. Les algorithmes natifs de QGIS doivent être disponibles (extension Traitements activée).

**English** — In QGIS 3.40 LTR or QGIS 4, use **Plugins → Manage and Install Plugins → Install from ZIP**, select `eurekarto_projection_tools-1_0_4.zip`, then enable the plugin. Both tools are available under **Plugins → Eurekarto Projection Tools** and in the plugins toolbar. No additional Python packages are required. Native QGIS algorithms must be available (Processing enabled).

The ZIP contains exactly one root folder, `eurekarto_projection_tools`. For manual installation, copy that folder into the active QGIS profile's `python/plugins` directory and restart QGIS. The package supports installation on QGIS 3.40–3.x and QGIS 4.x. Runtime regression tests were run with QGIS 3.40.5; a QGIS 4 runtime was not available, so full execution on QGIS 4 remains to be verified.

Migration references: [QGIS Qt 5 / Qt 6 migration guide](https://github.com/qgis/QGIS/wiki/Plugin-migration-to-be-compatible-with-Qt5-and-Qt6) and [plugin version-range rules](https://plugins.qgis.org/docs/migrate-qgis4).

## Antimeridian Cutter

1. Choose the project's destination CRS before opening the tool.
2. Select **Single layer** or **All project vector layers**. All mode takes a snapshot of valid spatial vector layers, including hidden layers and earlier results. Raster layers and attribute-only tables are excluded. A selection of features does not restrict the operation: the whole layer is processed.
3. Set the **cut half-width** (default `0.1°`, total width `0.2°`) and **mask densification step** (default `0.5°`).
4. The central meridian is read from `+lon_0`, an UTM zone, or a geographic CRS. If automatic detection is unavailable or inappropriate, enable the manual override and enter the central meridian as a WGS84 longitude. The cut is 180° from it. Non-Greenwich prime meridians require the manual override.
5. Optionally enable **Add mask** and **Hide original layers**, then run.

Workflow: repair lines/polygons with QGIS Linework → reproject to EPSG:4326 → difference with a densified antipodal band → reproject to the project CRS. Points do not need geometry repair. A band overlapping ±180° is written as two intervals, so its full width is preserved on both sides of the date line. Fields and attribute values are retained; feature IDs can change. The renderer and labeling configuration are copied where present. Joins, forms, relations, auxiliary storage and source-provider metadata are not cloned.

Results are named `<Original layer name> Projection Tool` and placed in **New layers**. The existing group is reused. These output names remain in English in either interface language. Original data is never edited. Original layer visibility changes only for layers with successful outputs. Per-layer failures are reported in the dialog; successful layers may still be published. Cancel discards all pending outputs from the current run. Optional mask display failure is reported separately and does not discard otherwise successful outputs.

### Scope of the cut

This removes a narrow strip; it is not a lossless split. Features entirely inside the strip disappear. The displayed mask spans **−89.9° to +89.9°** (`POLAR_LIMIT` in `antimeridian.py`): a band reaching exactly ±90° can turn invalid once reprojected for display in an interrupted projection. The cut itself also removes the two polar caps beyond that limit. Left in place, a cap would bridge the two sides of the band: harmless in a cylindrical projection, where a pole is a line along the map edge, but in a conic or azimuthal projection a pole becomes a point or recedes to infinity, and a feature around it — Antarctica in a projection centred on Europe — closes into a ring that covers the whole map. Features lose the 0.1° nearest each pole, which is invisible at any scale where the poles are shown. The caps carry a vertex at every grid step along their parallel, like the band along its meridian: reprojection moves vertices only, so an edge spanning 360° of longitude with two vertices would become a straight chord across the map. Input longitudes are expected in the conventional −180°…+180° domain after reprojection. The tool does not unwrap geometries encoded in a 0°…360° domain or infer intended great-circle paths. It cuts one antipodal meridian, not all the internal seams of an interrupted projection. Densification applies to the mask's vertical edges, not every source geometry edge. Source features with sparse vertices may need separate densification before reprojection.

The optional display mask crosses the projection seam by design; in some projections its display may be distorted. It is a diagnostic layer, not a projection-domain outline. Use Projection Outline for that purpose.

## Projection Outline

Choose **Contour - Line** or **Contour - Polygon**. The method is a grid transformed cell by cell, then dissolved:

- Construct a global geographic grid between latitudes −89.999° and +89.999° (default step `1°`).
- Transform shared grid vertices into the project's CRS, retaining custom CRSs without an authority code.
- Reject cells with invalid transformed coordinates, invalid/zero-area polygons, or an edge longer than the chosen threshold.
- Dissolve accepted cells and repair the domain. For line output, extract its boundary.

The default maximum edge is **500,000 metres**, converted to the projected CRS's units. A geographic project uses **5 degrees**. The dialog explicitly shows the project CRS units. Step range: `0.25°` to `5°`. Smaller steps create more cells and take longer. The threshold and step must be adjusted together: an overly low threshold drops valid cells; an overly high threshold can bridge an interruption. The produced outline is an **approximation**, not an analytic boundary or the CRS's formal area of use. It can contain holes or small gaps. The method supports interrupted projections such as **World_Goode_Homolosine_Ocean (ESRI:54053)** but no fixed parameter pair guarantees all projection domains. Mercator and other unbounded projections are necessarily limited by the grid and threshold.

Outputs are named `Contour - Line` or `Contour - Polygon` and placed in **New layers**. Polygon output is initially styled with a transparent interior.

## Temporary results / Résultats temporaires

**Français** — Les résultats sont des couches temporaires en mémoire. **Enregistrer le projet ne suffit pas à conserver leurs données.** Exportez-les, par exemple dans un GeoPackage, avant de fermer QGIS. Le traitement peut durer plusieurs minutes sur une grille fine ou de grosses couches. L’annulation est coopérative : une opération native de dissolution ou de géométrie peut mettre du temps à rendre la main.

**English** — Results are temporary memory layers. **Saving the QGIS project alone does not save their data.** Export them, for example to a GeoPackage, before closing QGIS. Fine grids and large datasets can take several minutes. Cancellation is cooperative: a native dissolve or geometry operation can take time to return control.

## Languages

English is the source language. The plugin loads the French Qt translation catalog when QGIS's locale is French (`fr`, `fr_FR`, etc.). Other locales use English. Restart/reload the plugin after changing QGIS's language. Both editable `.ts` files and loadable `.qm` catalogs are included. Standard Qt controls use QGIS/Qt translations; errors emitted by native Processing algorithms follow QGIS's own language. To rebuild a catalog with Qt Linguist tools:

```sh
lrelease i18n/eurekarto_projection_tools_fr.ts -qm i18n/eurekarto_projection_tools_fr.qm
```

## Package structure

```text
eurekarto_projection_tools/
  __init__.py
  metadata.txt
  plugin.py
  common.py
  antimeridian.py
  outline.py
  dialogs/
    __init__.py
    base.py
    antimeridian_dialog.py
    outline_dialog.py
  i18n/
    eurekarto_projection_tools_en.ts
    eurekarto_projection_tools_en.qm
    eurekarto_projection_tools_fr.ts
    eurekarto_projection_tools_fr.qm
  img/icon.png
  README.md
  LICENSE
```

This plugin exposes its own dialogs; it does not register a separate Processing provider. Its processing modules call QGIS's native algorithms.

## Development and references

The implementation follows the [QGIS 3.40 plugin structure](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/plugins/plugins.html) and uses the [QGIS 3.40 CRS API](https://api.qgis.org/api/3.40/classQgsCoordinateReferenceSystem.html).

## Checks run on this package

- **Unit tests** — 31 tests, three of them replaying a conic projection centred on Europe with PROJ when `shapely` and `pyproj` are installed — reprojecting vertex by vertex, without densifying, as QGIS does — covering longitude normalisation, central meridian detection (`+lon_0`, UTM zone, geographic CRS, shifted prime meridian, unreadable projection), the antipodal band and its wrap at ±180°, mask latitudes, parameter bounds, and grid cell rejection. They run without QGIS, on minimal stand-ins: `python3 test_projection_tools.py`.
- **Static analysis** — `pyflakes` and `flake8` (lines ≤ 100 characters, complexity ≤ 12) report nothing.
- **Translations** — 49 strings, every displayed label present in both catalogs, none unused.
- **Not verified** — execution inside QGIS 4, and any behaviour depending on native algorithms. Test on a real project before distribution.

## Changelog

- **1.0.4** — Polar caps densified along their parallel; 1.0.3 still let Antarctica cover the map in a conic projection.
- **1.0.3** — The cut also removes both polar caps, so Antarctica no longer covers the map in conic or azimuthal projections centred away from the date line.
- **1.0.2** — Contact and repository declared. The two long routines split into readable units; named constants for the polar limit, the parameter ranges and the symbol colours; the version number read from a single place; unit tests added. No change to what the tools produce.
- **1.0.1** — Qt 5 / Qt 6 compatibility: imports, scoped enums, dialog execution.
- **1.0.0** — First release.
