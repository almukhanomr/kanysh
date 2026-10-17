# Petrel / RMS exchange guide · Инструкция обмена

Kanysh Basic works alongside Petrel/RMS using exported exchange files. It does not
open native Petrel project databases or RMS project directories. Choose the format,
not a specific vendor release. Export a copy into one folder; preserve relative
INCLUDE paths. This guide targets English object names, with Russian explanations.

**Menu status:** the navigation below is a workflow guide, not a verified click-by-click
procedure for every release. Exact labels, licences and enabled exporters vary.
Petrel/RMS GUI acceptance: **NOT RUN**. Use the application's local Help for the named
export format if the context menu differs. Do not rename a proprietary file to `.DATA`.

| Object / Объект | Export / Выгрузка | What it enables / Для чего |
|---|---|---|
| Grid geometry / Геометрия | ECLIPSE ASCII GRDECL: SPECGRID/DIMENS, COORD, ZCORN, ACTNUM; preferably the complete static DATA + all INCLUDE files | Block import, geometry QC, 3D, regional scenarios. Current large-grid route is ASCII DATA/GRDECL. |
| Static properties / Свойства | PORO, NTG, PERMX, SWAT; FIPNUM, EQLNUM, SATNUM; optional PERMY/PERMZ, same IJK grid | Pore/hydrocarbon volumes, regional selection, property QC. SWATINIT is **not** a calculated SWAT. Missing fields require explicit user input. |
| Binary grid / Бинарная сетка | EGRID or binary ROFF + explicit property manifest | XTGeo route with full-RAM geometry and current 2M-cell cap; do not use it for the 20M ASCII benchmark claim. |
| Depth surfaces / Поверхности | IRAP/RMS classic ASCII or binary (preferred); ZMAP+; CPS-3 **ASCII** | Scene overlay; declared units, depth sign and CRS/datum. CPS-3 requires explicit sample order/Y direction. |
| Well surveys / Траектории | RMS well ASCII, or Petrel ASCII/CSV with well ID, MD, X, Y, Z | 3D paths and model/LAS point comparison. MD, TVD, TVDSS and elevation are different quantities. XYZ/MD are required; inclination/azimuth alone are not converted automatically. |
| Tops / Разбивки | ASCII/CSV: well ID, marker name and MD (or explicit XYZ) | Marker display; MD-only tops need an imported trajectory. No automatic stratigraphic correlation. |
| Logs / ГИС | Original LAS, original null code, depth/curve units and well identity | Compare mapped PORO/NTG curves to model cells; preserve original curves, do not export only screenshots. |
| Polygons / Полигоны | ASCII/CSV: polygon ID and ordered closed X/Y/Z rings | Scene and whole-cell regional selection. State outer/hole IDs and boundary policy. |
| Seismic / Сейсмика | Sorted regular zero-offset poststack SEG-Y (IBM/IEEE float32) | Streaming tiles, slices and scene. Confirm inline/crossline/coordinate headers and TWT/depth units. Prestack/unsorted volumes are unsupported. |
| Volume report / Отчёт объёмов | CSV: region ID, metric, numeric value, unit (long form) | Reconciliation. Confirm GRV/NRV/PV/HCPV/STOIIP/GIIP definitions, active mask, contacts, Bo/Bg, NTG cutoffs, region meaning. |

## Petrel: navigation / Порядок в Petrel

1. In **Models**, select the 3D grid and use its **Export…** context action.
   In the format selector look for **ECLIPSE / GRDECL ASCII** geometry/keywords.
   Export ACTNUM and properties from the same grid. For a simulation case use its
   ECLIPSE export workflow to obtain DATA plus includes; the simulator need not run.
2. In **Input**, select a surface and use **Export…**; choose IRAP classic/binary
   or ZMAP+. Export depth values with declared datum, not an image of a map.
3. Under wells, export surveys/trajectories, tops and logs separately using the
   respective ASCII/LAS exporters. Keep headers and well names. For generic ASCII
   provide column names/indices, skipped header rows and units to the agent.
4. Export polygons as ordered coordinates, and the volume-results table as CSV.
   If the table is wide (one metric per column), reshape a copy into
   `region_id,metric,value,unit`; preserve the original report for audit.

Эти названия — ориентиры интерфейса, а не обещание одинаковых меню во всех версиях.
Выберите сетку в Models и действие Export, затем формат ECLIPSE/GRDECL ASCII.
Для поверхностей используйте Input → объект поверхности → Export и IRAP/ZMAP+.
Траектории, разбивки, LAS и таблицу объёмов выгружайте отдельными файлами.
Не меняйте исходные данные, единицы или систему координат ради импорта.

## RMS: navigation / Порядок в RMS

Select a grid model/property in **Grid models**, then use the object's **Export**
action or the export job in your release's workflow/job manager. Select ECLIPSE
ASCII/GRDECL, including active mask and required properties. In **Horizons** select
the surface/category and its export action; prefer **IRAP binary** to retain rotation.
In **Wells**, export RMS well ASCII surveys and original LAS separately. Use the
points/polygons and well-picks exporters for ordered rings and tops. Export the
volume table with explicit region IDs/units. RMS export-job menu labels are
**version-dependent and not GUI-verified here**.

В RMS откройте Grid models, выберите сетку/свойства и Export либо задание экспорта
в workflow/job manager вашей версии. Для горизонтов выберите поверхность и категорию;
предпочтителен IRAP binary. В Wells выгрузите RMS well ASCII и исходные LAS отдельно.
Сохраните единый IJK и точные названия регионов. Если экспорт недоступен, используйте
справку установленной версии или администратора лицензий.

## Before calculating / Перед расчётом

Tell the copilot the horizontal CRS, vertical datum, coordinate/MD units, positive-Z
convention, region definition, contacts and PVT basis. `folder_assess` only proposes
values with file/line evidence. Confirm them explicitly before a plan. A PVT table
alone does not establish one Bo without pressure/temperature/fluid-region selection.
Header absence is not evidence of a local/UTM coordinate system.

Сообщите CRS, datum, единицы, знак Z, определение регионов, контакты и основу PVT.
Предложения `folder_assess` подтвердите до плана. Неизвестные значения остаются
неизвестными; неподдерживаемые ключевые слова видны в отчёте импорта.

Format references (vendor menus remain unverified):
- [XTGeo format data model](https://xtgeo.readthedocs.io/en/stable/datamodels.html)
- [XTGeo surface reader API and formats](https://xtgeo.readthedocs.io/en/latest/_modules/xtgeo/surface/regular_surface.html)
- [RMS surface export examples](https://xtgeo.readthedocs.io/en/latest/tutorial/examples_rms.html)
- [OPM ECLIPSE INCLUDE](https://opm.github.io/opm-flow-editor-support/keywords/INCLUDE.html)
