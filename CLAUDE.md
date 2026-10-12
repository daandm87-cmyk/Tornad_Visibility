# Tornado Visibility Forecast Tool: project context

Storm-chaser tool by Daan (downburstdaan.com). Forecasts **how visible a tornado
will be** (LP / Classic / HP storm mode) from HRRR model data, rendered as HTML
slider maps. Built iteratively in a claude.ai chat (Apr–Jun 2026); this file
carries that context forward.

The user is **red-green colorblind**: never use red/green opposition in colormaps.

---

## Files

| File | Role |
|---|---|
| `chase_beauty.py` | Core library: `compute_hour()` (download + physics) and `render_hour(result, ..., extent=None)` (plotting). Also a CLI for a single F00 map. All tunables live at the top. |
| `chase_slider.py` | `build_html(frames, run_time)`: self-contained dark-theme HTML slider (play/pause, arrow keys, diagnostics panel). PNGs embedded as base64. |
| `hrrr_utils.py` | `recent_run_time()`, `latest_complete_run()`, `load_hrrr()`, `find_dataset_with()`. Forces UTF-8 stdout (Windows cp1252 crash fix). |
| `chase_window.py` | **Local** use: 21Z–01Z window, single full-domain HTML (`tornado_visibility_chase_window.html`). |
| `chase_window_online.py` | **GitHub Actions** use: 21Z–03Z window. Computes each hour ONCE, then renders 7 extents to `docs/index.html` + `docs/{texas,oklahoma,kansas,nebraska,south_dakota,iowa}.html`. |
| `inspect_fields.py`, `inspect_cube11.py` | Diagnostics for HRRR hypercube contents. Not part of the workflow. |
| `.github/workflows/render.yml` | On-demand (`workflow_dispatch`) workflow: conda env, run `chase_window_online.py`, commit `docs/`. Served via GitHub Pages from `/docs`, embedded on the user's Google Site as separate iframes. |
| `environment.yml` | conda-forge, Python 3.11: herbie-data, metpy, cartopy, cfgrib, matplotlib, numpy, xarray, scipy. **Unpinned**, see Known issues. |

`chase_window_states.py` and `chase_slider_12h.py` are obsolete (merged into
`chase_window_online.py` / superseded). Delete if present.

Live site: https://daandm87-cmyk.github.io/Tornad_Visibility/

---

## HRRR field mappings (verified on real data, NOT assumed)

cfgrib splits HRRR into ~46 sfc + ~43 prs hypercubes. Cube indices can shift,
so code locates cubes by variable/coordinate via `find_dataset_with()`.

| Field | Source | Notes |
|---|---|---|
| MLCAPE | sfc `cape` with `pressureFromGroundLayer=9000` | The `cape` at `heightAboveGroundLayer=0` is a cfgrib artifact (~216 J/kg garbage). |
| Storm motion | sfc `ustm`, `vstm` | Values fine despite broken level metadata. |
| 0–6 km bulk shear | **computed**: prs 500mb wind minus sfc 10m wind | `vucsh`/`vvcsh` are broken (mislabeled, degenerate level). |
| 0–1 km SRH | sfc `hlcy` at `heightAboveGroundLayer=1000` | 3000 also available. |
| LCL | sfc `gh` at `adiabaticCondensation` minus `orog` | `gh` is AMSL; subtract orography for AGL. |
| PW | sfc `pwat` (kg/m² ÷ 25.4 = inches) | |
| Reflectivity | sfc `refc` | Labeled dB, values are dBZ. |
| Upper winds | prs `u`/`v` on `isobaricInhPa` (1000,925,850,700,500,300,250) | |
| 80 m wind | sfc `u`/`v` with scalar `heightAboveGround=80` | |
| "1000 m wind" | **sfc cube 11 is NOT usable** | Verified via GRIB metadata: `stepType='max'` hourly-max diagnostic; 10m level duplicates u10, 1000m level is mostly zeros. |

Plotting gotcha: HRRR is on a Lambert grid with x/y indices. Every `.plot()`
call needs `x="longitude", y="latitude"` and `transform=ccrs.PlateCarree()`.

The `nat` (native-level) product would give true winds at any height but is
5–8x larger per hour. Rejected for bandwidth reasons.

---

## Physics

**STP**: MetPy `significant_tornado(mlcape, lcl_agl, srh01, shear06)`, clipped
at 0 (MetPy goes negative when LCL > 2000 m). Mode is only drawn where
STP > `STP_MASK` (0.5).

**Mode index** (0 = HP, 0.5 = Classic, 1 = LP):

```
sr_term   = ramp(anvil SR wind, 40 -> 60 kt)    # 300mb wind minus storm motion
llsr_term = ramp(10m SR wind,   20 -> 50 kt)    # 10m wind minus storm motion
pw_term   = +/-0.12 from precipitable water     # neutral 1.5", dry sat 0.5", wet sat 2.0"
mode      = clip(max(sr_term, llsr_term) + pw_term, 0, 1)
```

The `max()` encodes two independent ventilation pathways: strong anvil-level
SR flow OR strong low-level SR inflow can each keep the tornado visible. The
anvil thresholds (40/50/60 kt) were checked against SPC 9–11 km SR wind
mesoanalysis; don't change them casually.

**Critical angle** (Esterheld & Giuliano 2008): angle between the 10m
storm-relative wind and the 0–500m shear vector. 500m wind is linearly
interpolated between 80m wind and 925mb wind (925mb assumed at 762 m MSL,
standard atmosphere). Interpolation was chosen over substituting 0–1km shear
because on clockwise-curved hodographs the 0–1km vector is rotated relative
to 0–500m, which distorts the angle more than interpolation error does.
Masked where terrain > 1200 m, SR wind < 2 m/s, or shear < 1 m/s. Shown only
for the 85–95° band, only inside the STP mask.

---

## Visual design

- Colormap `_CMAP_STOPS`: purple to blue (HP), hard edge to a flat teal block
  (Classic, 0.40–0.60), hard edge to yellow-green to yellow (LP). Hard edges use
  stops offset by 0.0001 (newer matplotlib rejects duplicate positions).
- Black contour: 30 dBZ reflectivity (gaussian sigma=1), shows where HRRR fires storms.
- Critical angle: light-grey `////` hatch, semi-transparent, thin outline.
  **Rejected alternatives** (user disliked): white outline (lost on yellow),
  magenta stippling (cluttered at any density).
- Hatch gotchas: `contourf(colors='none', hatches=...)` can paint hatch across
  the whole axes. Use a real low-alpha fill color, style via
  `mpl.rc_context({"hatch.color": ...})`, and skip drawing when the favorable
  region is empty. The user reported hatch covering the whole map even after
  the first fix; confirm the current version renders correctly before building on it.

---

## Calibration log

Treat these as ground truth for tuning. One event is not a trend.

- **2026-04-29, West TX (I-10, Ozona area).** Tool showed LP/Classic in a
  bright-yellow strip; HRRR initiation location was accurate. Reality: isolated
  long-lived Classic/low-end-HP supercell, baseball hail, no tornado. Structure
  washed out by haze that worsened with distance (likely dust/aerosol; RH only
  ~70%). Mode prediction judged correct; haze is outside the tool's scope.
- **2026-06-11, northern Illinois.** Tool (anvil SR + PW only) showed solid HP.
  SPC mesoanalysis confirmed anvil SR 20–30 kt and PW 1.8–2.1", so inputs were
  read correctly, and human consensus also expected an HP mess. Reality:
  multiple clearly visible tornadoes; discrete cells moving 40–50 mph, tops
  14–17 km, temps low-mid 80s, dewpoints low-mid 70s. Diagnosis: strong
  low-level SR inflow ventilated the meso. Led to the `llsr_term`. A first
  additive version (+0.25 max) was too weak to change the colors; replaced
  with the `max()` formulation, after which the map showed some
  visible-tornado spots. **Watch for:** a slow-moving, high-PW day should still
  render purple. If everything drifts teal, the term is overcorrecting.

---

## Workflow notes

- HRRR has no "run complete" flag on AWS. `latest_complete_run()` probes Herbie
  (fast existence check, no download) for the deepest forecast hour needed,
  walking back from the current hour.
- `compute_hour()` failures are caught per-hour and skipped, so one missing
  file doesn't kill the run.
- Keep the GitHub Actions load light: one compute pass, re-render only.
- The user is learning git and previously pushed single files by hand; a
  missed file caused one failed run. Commit all files a change touches.

---

## Known issues / open ideas

- **Pin versions in `environment.yml`.** Unpinned matplotlib already broke a
  run mid-season (colormap stop rule change). Pin to known-good versions.
- Effective-layer SRH instead of fixed 0–1 km (closer to SPC's STP).
- MLLCL instead of SBLCL proxy.
- Possible haze/visibility factor (dry boundary layer, HRRR `vis`). Deferred
  until more cases.
- Archive playback of historic events for calibration.
- Node.js 20 deprecation warnings on `actions/checkout@v4` and
  `setup-miniconda@v3`: bump versions when newer releases exist.
