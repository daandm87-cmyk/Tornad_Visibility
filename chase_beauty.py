"""Tornado visibility forecast from HRRR.

Two layers:
  • Base — storm-mode color, shown only where STP > mask.
           Driven mostly by storm-relative anvil-level wind, with a minor
           tweak from precipitable water at the extremes.
  • Top  — single black contour at 30 dBZ simulated reflectivity, so you can
           see where HRRR actually fires storms.

Run as a script for the analysis (F00) hour only:
    python chase_beauty.py

Or import render_hour() from another script (see chase_slider.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import metpy.calc as mpcalc
from scipy.ndimage import gaussian_filter

from hrrr_utils import recent_run_time, load_hrrr, find_dataset_with


# ---------------------------------------------------------------------------
# Tunable thresholds — adjust as you calibrate against real chase outcomes
# ---------------------------------------------------------------------------
SR_KT_LP_FLOOR    = 40.0    # ≤ this  → red end (HP)
SR_KT_LP_CEIL     = 60.0    # ≥ this  → bright end (LP); 50 kt = Classic mid
PW_NEUTRAL_IN     = 1.5
PW_DRY_RANGE_IN   = 1.0
PW_WET_RANGE_IN   = 0.5
PW_WEIGHT         = 0.12
STP_MASK          = 0.5
REFC_CONTOUR_DBZ  = 30.0
REFC_SMOOTH_SIGMA = 1.0
REFC_LINEWIDTH    = 0.6
PLOT_EXTENT       = [-107, -85, 25, 49]

# Critical angle (Esterheld & Giuliano 2008) — favorable band where surface
# inflow is roughly perpendicular to 0-500m shear (purely streamwise vorticity).
# We approximate 500m AGL wind by interpolating between 80m and 925mb winds,
# treating 925mb as ~762m MSL (standard atmosphere). Rendered as magenta
# stippled dots so the band reads as a "look here" highlight rather than
# competing as another map layer.
CRIT_ANGLE_MIN_DEG   = 85.0
CRIT_ANGLE_MAX_DEG   = 95.0
CRIT_ANGLE_OROG_MAX  = 1200.0    # mask cells above this elevation (High Plains)
CRIT_ANGLE_STIPPLE_STRIDE = 18   # every nth grid cell gets a dot (higher = sparser)
CRIT_ANGLE_STIPPLE_SIZE   = 8    # marker size in points
CRIT_ANGLE_STIPPLE_COLOR  = "#ff00d4"   # hot magenta
STD_ATM_Z_925_MSL    = 762.0     # standard atmosphere 925 mb height, meters


# ---------------------------------------------------------------------------
# Colormap — piecewise so Classic (~50 kt → mode 0.5) gets its own block
# while HP and LP zones retain smooth gradients on either side.
# Colorblind-safe (no red/green opposition).
# ---------------------------------------------------------------------------
_CMAP_STOPS = [
    (0.00, "#3b0a4a"),   # deep purple — strongest HP
    (0.40, "#3a72b8"),   # blue — edge of HP zone (sharp jump from here ↓)
    (0.40, "#1fb89a"),   # teal — start of Classic band
    (0.60, "#1fb89a"),   # teal — end of Classic band
    (0.60, "#a8d63a"),   # yellow-green — start of LP zone (sharp jump ↑)
    (1.00, "#fce91a"),   # bright yellow — strongest LP
]
MODE_CMAP = LinearSegmentedColormap.from_list("hp_classic_lp", _CMAP_STOPS)


# ---------------------------------------------------------------------------
# Data class for the per-hour result
# ---------------------------------------------------------------------------
@dataclass
class HourResult:
    valid_time: object   # numpy datetime64 or python datetime
    mode: object         # xarray DataArray (NaN outside STP mask)
    refc_smooth: object  # xarray DataArray of smoothed reflectivity
    critical_angle: object   # xarray DataArray of critical angle in degrees
    diagnostics: dict


# ---------------------------------------------------------------------------
# Per-hour computation, factored out so the slider can reuse it
# ---------------------------------------------------------------------------
def compute_hour(run_time, fxx: int) -> HourResult:
    """Run the full pipeline for one HRRR forecast hour and return arrays."""
    sfc_list = load_hrrr(run_time, product="sfc", fxx=fxx)
    prs_list = load_hrrr(run_time, product="prs", fxx=fxx)

    ds_cape  = find_dataset_with(sfc_list, "cape", require_coord="pressureFromGroundLayer")
    ds_storm = find_dataset_with(sfc_list, "ustm", "vstm")
    ds_10m   = find_dataset_with(sfc_list, "u10", "v10")
    ds_hlcy  = find_dataset_with(sfc_list, "hlcy")
    ds_lcl   = find_dataset_with(sfc_list, "gh", require_coord="adiabaticCondensation")
    ds_orog  = find_dataset_with(sfc_list, "orog")
    ds_pw    = find_dataset_with(sfc_list, "pwat")
    ds_refc  = find_dataset_with(sfc_list, "refc")
    ds_prs   = find_dataset_with(prs_list, "u", "v", require_coord="isobaricInhPa")

    # Explicit lookup for the 80m wind cube — needs to be scalar heightAboveGround=80,
    # to disambiguate from any other sfc cube that happens to have u/v fields.
    ds_80m = None
    for ds in sfc_list:
        if ("u" in ds.data_vars and "v" in ds.data_vars
                and "heightAboveGround" in ds.coords
                and ds.heightAboveGround.size == 1
                and float(ds.heightAboveGround) == 80.0):
            ds_80m = ds
            break

    for label, ds in [("MLCAPE", ds_cape), ("storm motion", ds_storm),
                      ("10 m winds", ds_10m), ("0-1 km helicity", ds_hlcy),
                      ("LCL", ds_lcl), ("orography", ds_orog),
                      ("precipitable water", ds_pw),
                      ("composite reflectivity", ds_refc),
                      ("pressure-level winds", ds_prs),
                      ("80 m winds", ds_80m)]:
        if ds is None:
            raise RuntimeError(f"Could not find {label} hypercube at fxx={fxx}.")

    ds_cape  = ds_cape.metpy.parse_cf()
    ds_storm = ds_storm.metpy.parse_cf()
    ds_10m   = ds_10m.metpy.parse_cf()
    ds_hlcy  = ds_hlcy.metpy.parse_cf()
    ds_lcl   = ds_lcl.metpy.parse_cf()
    ds_orog  = ds_orog.metpy.parse_cf()
    ds_pw    = ds_pw.metpy.parse_cf()
    ds_refc  = ds_refc.metpy.parse_cf()
    ds_prs   = ds_prs.metpy.parse_cf()
    ds_80m   = ds_80m.metpy.parse_cf()

    # MLCAPE (90 mb mixed-layer parcel)
    mlcape = ds_cape["cape"].sel(pressureFromGroundLayer=9000).metpy.quantify()

    # Storm motion
    storm_u = ds_storm["ustm"].metpy.quantify()
    storm_v = ds_storm["vstm"].metpy.quantify()

    # Bulk shear: sfc → 500 mb (computed manually; vucsh is broken)
    u_sfc = ds_10m["u10"].metpy.quantify()
    v_sfc = ds_10m["v10"].metpy.quantify()
    u500 = ds_prs["u"].sel(isobaricInhPa=500).metpy.quantify()
    v500 = ds_prs["v"].sel(isobaricInhPa=500).metpy.quantify()
    shear06 = np.sqrt((u500 - u_sfc) ** 2 + (v500 - v_sfc) ** 2)

    # 0-1 km SRH
    srh01 = ds_hlcy["hlcy"].sel(heightAboveGroundLayer=1000.0).metpy.quantify()

    # LCL AGL
    lcl_agl_da = (ds_lcl["gh"] - ds_orog["orog"]).clip(min=0)
    lcl_agl_da.attrs["units"] = "m"
    lcl_agl = lcl_agl_da.metpy.quantify()

    # 300 mb winds
    u300 = ds_prs["u"].sel(isobaricInhPa=300).metpy.quantify()
    v300 = ds_prs["v"].sel(isobaricInhPa=300).metpy.quantify()

    sr_speed = np.sqrt((u300 - storm_u) ** 2 + (v300 - storm_v) ** 2)
    sr_kt = sr_speed.metpy.convert_units("knots").metpy.dequantify()

    stp = mpcalc.significant_tornado(mlcape, lcl_agl, srh01, shear06)
    stp_vals = stp.metpy.dequantify().clip(min=0)

    # Mode index
    sr_term = ((sr_kt - SR_KT_LP_FLOOR) / (SR_KT_LP_CEIL - SR_KT_LP_FLOOR)).clip(0, 1)
    pwat_in = ds_pw["pwat"] / 25.4
    dry_bonus   = ((PW_NEUTRAL_IN - pwat_in) / PW_DRY_RANGE_IN).clip(0, 1)
    wet_penalty = ((PW_NEUTRAL_IN - pwat_in) / PW_WET_RANGE_IN).clip(-1, 0)
    pw_term = (dry_bonus + wet_penalty) * PW_WEIGHT
    mode = (sr_term + pw_term).clip(0, 1).where(stp_vals > STP_MASK)

    # ---- Critical Angle ----------------------------------------------------
    # Angle between 10m storm-relative wind and 0-500m AGL shear vector.
    # 500m wind is estimated by linear interpolation between 80m wind and 925mb
    # wind, treating 925mb as ~762m MSL (standard atmosphere). Cells where 925mb
    # is at or below the surface (orog > CRIT_ANGLE_OROG_MAX) are masked.
    u80 = ds_80m["u"]
    v80 = ds_80m["v"]
    u925 = ds_prs["u"].sel(isobaricInhPa=925)
    v925 = ds_prs["v"].sel(isobaricInhPa=925)
    u10_da = ds_10m["u10"]
    v10_da = ds_10m["v10"]
    storm_u_da = ds_storm["ustm"]
    storm_v_da = ds_storm["vstm"]
    orog_da = ds_orog["orog"]

    z_925_agl = STD_ATM_Z_925_MSL - orog_da              # meters AGL
    frac = (500.0 - 80.0) / (z_925_agl - 80.0)            # fraction from 80m to 925m
    u_500 = u80 + frac * (u925 - u80)
    v_500 = v80 + frac * (v925 - v80)

    # 10m storm-relative wind vector
    sr_u_10 = u10_da - storm_u_da
    sr_v_10 = v10_da - storm_v_da
    # 0-500m shear vector
    shear_u_05 = u_500 - u10_da
    shear_v_05 = v_500 - v10_da

    dot_ca = sr_u_10 * shear_u_05 + sr_v_10 * shear_v_05
    mag_sr_10 = np.sqrt(sr_u_10 ** 2 + sr_v_10 ** 2)
    mag_shear_05 = np.sqrt(shear_u_05 ** 2 + shear_v_05 ** 2)
    cos_ca = (dot_ca / (mag_sr_10 * mag_shear_05)).clip(-1.0, 1.0)
    critical_angle = np.degrees(np.arccos(cos_ca))

    # Mask cells with degenerate geometry or high terrain
    ca_mask = (
        (mag_sr_10 > 2.0) &
        (mag_shear_05 > 1.0) &
        (orog_da < CRIT_ANGLE_OROG_MAX)
    )
    critical_angle = critical_angle.where(ca_mask)

    # Reflectivity smoothing
    refc = ds_refc["refc"]
    refc_data = (gaussian_filter(refc.values, sigma=REFC_SMOOTH_SIGMA)
                 if REFC_SMOOTH_SIGMA > 0 else refc.values)
    refc_smooth = refc.copy(data=refc_data)

    diagnostics = {
        "mlcape_max": float(mlcape.max()),
        "srh01_max": float(srh01.max()),
        "shear06_max": float(shear06.metpy.dequantify().max()),
        "lcl_med": float(lcl_agl_da.median()),
        "sr_kt_max": float(sr_kt.max()),
        "stp_min": float(stp_vals.min()),
        "stp_max": float(stp_vals.max()),
        "refc_max": float(refc.max()),
        "stp_pixels": int((stp_vals > STP_MASK).sum()),
        "ca_favorable_pixels": int(
            ((critical_angle >= CRIT_ANGLE_MIN_DEG) &
             (critical_angle <= CRIT_ANGLE_MAX_DEG)).sum()
        ),
    }

    return HourResult(
        valid_time=ds_refc.valid_time.values,
        mode=mode,
        refc_smooth=refc_smooth,
        critical_angle=critical_angle,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Plot one hour onto an existing axes (or create one if ax is None)
# ---------------------------------------------------------------------------
def render_hour(result: HourResult, ax=None, run_time=None, fxx: int | None = None):
    """Draw the visibility map for a single HourResult."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(13, 8.5),
                               subplot_kw={"projection": ccrs.PlateCarree()})
    else:
        fig = ax.figure

    plot_kw = dict(x="longitude", y="latitude", transform=ccrs.PlateCarree())

    mode_plot = result.mode.plot(
        ax=ax, **plot_kw,
        cmap=MODE_CMAP, vmin=0, vmax=1,
        cbar_kwargs={"label": "Storm mode",
                     "shrink": 0.75, "pad": 0.02,
                     "ticks": [0.0, 0.5, 1.0]},
    )
    mode_plot.colorbar.ax.set_yticklabels(["HP\n(≤40 kt)",
                                           "Classic\n(50 kt)",
                                           "LP\n(≥60 kt)"])

    result.refc_smooth.plot.contour(
        ax=ax, **plot_kw,
        levels=[REFC_CONTOUR_DBZ],
        colors="black",
        linewidths=REFC_LINEWIDTH,
    )

    # Stippling for the favorable critical-angle band (85-95° = near-perfect
    # streamwise vorticity ingestion). Magenta dots at every Nth grid cell —
    # high contrast against every color in the storm-mode colormap, doesn't
    # compete with the black precip contour, reads as "look here" waypoints.
    ca = result.critical_angle
    favorable_mask = (
        (ca >= CRIT_ANGLE_MIN_DEG) & (ca <= CRIT_ANGLE_MAX_DEG)
    ).values   # bool ndarray, shape (y, x)
    # Subsample on a regular stride so dot density is controllable.
    stride = CRIT_ANGLE_STIPPLE_STRIDE
    sub_mask = favorable_mask[::stride, ::stride]
    if sub_mask.any():
        lon2d = ca["longitude"].values[::stride, ::stride]
        lat2d = ca["latitude"].values[::stride, ::stride]
        ax.scatter(
            lon2d[sub_mask], lat2d[sub_mask],
            s=CRIT_ANGLE_STIPPLE_SIZE,
            c=CRIT_ANGLE_STIPPLE_COLOR,
            marker="o",
            edgecolors="none",
            transform=ccrs.PlateCarree(),
            zorder=5,
        )

    ax.add_feature(cfeature.STATES, linewidth=0.5, edgecolor="black")
    ax.add_feature(cfeature.COASTLINE, linewidth=0.6)
    ax.add_feature(cfeature.BORDERS, linewidth=0.6)
    ax.set_extent(PLOT_EXTENT)

    valid_str = np.datetime_as_string(result.valid_time, unit="m").replace("T", " ")
    title_lines = [f"Tornado Visibility Forecast — Valid {valid_str} UTC"]
    if run_time is not None and fxx is not None:
        title_lines[0] += f"   (HRRR {run_time:%Y-%m-%d %H} UTC + F{fxx:02d})"
    title_lines.append(
        f"Color = storm mode  |  "
        f"Black contour = {REFC_CONTOUR_DBZ:.0f} dBZ reflectivity  |  "
        f"Magenta dots = critical angle {CRIT_ANGLE_MIN_DEG:.0f}–{CRIT_ANGLE_MAX_DEG:.0f}°  |  "
        f"Masked to STP > {STP_MASK}"
    )
    ax.set_title("\n".join(title_lines), fontsize=11)

    return fig, ax


# ---------------------------------------------------------------------------
# CLI: render a single F00 map (the original script behavior)
# ---------------------------------------------------------------------------
def main() -> None:
    run_time = recent_run_time()
    print(f"HRRR run: {run_time:%Y-%m-%d %H:%M UTC}")

    result = compute_hour(run_time, fxx=0)

    d = result.diagnostics
    print(f"MLCAPE max:  {d['mlcape_max']:>7.0f} J/kg")
    print(f"SRH01 max:   {d['srh01_max']:>7.0f} m²/s²")
    print(f"Shear06 max: {d['shear06_max']:>7.1f} m/s")
    print(f"LCL-AGL med: {d['lcl_med']:>7.0f} m")
    print(f"SR300 max:   {d['sr_kt_max']:>7.1f} kt")
    print(f"STP range:   {d['stp_min']:.2f} – {d['stp_max']:.2f}")
    print(f"refc max:    {d['refc_max']:>7.1f} dBZ")
    print(f"Pixels with STP > {STP_MASK}: {d['stp_pixels']:,}")
    print(f"Pixels with critical angle {CRIT_ANGLE_MIN_DEG:.0f}–{CRIT_ANGLE_MAX_DEG:.0f}°: "
          f"{d['ca_favorable_pixels']:,}")

    fig, _ = render_hour(result, run_time=run_time, fxx=0)
    plt.tight_layout()

    out = "tornado_visibility.png"
    plt.savefig(out, dpi=200, bbox_inches="tight")
    print(f"✅ Saved {out}")
    plt.show()


if __name__ == "__main__":
    main()
