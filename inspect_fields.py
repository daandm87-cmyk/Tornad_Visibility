"""Deep dump of every HRRR variable across every hypercube + sanity probes.

Usage:
    python inspect_fields.py > fields.txt

Looks for:
  • CAPE flavors (SBCAPE / MLCAPE / MUCAPE) — we currently use SBCAPE which
    collapses at 12Z in early morning; we want MLCAPE.
  • Real names behind the cfgrib 'unknown' labels (via GRIB_* attrs).
  • Sanity probes: max value of refc, all CAPE-like fields, lat/lon ranges.
"""
from hrrr_utils import recent_run_time, load_hrrr


GRIB_KEYS = ("GRIB_shortName", "GRIB_name", "GRIB_cfName", "GRIB_cfVarName",
             "GRIB_paramId", "GRIB_typeOfLevel", "GRIB_stepType")


def describe_var(ds, v: str) -> str:
    a = ds[v].attrs
    long_name = a.get("long_name", a.get("GRIB_name", "?"))
    units = a.get("units", "?")
    base = f"  {v:18s} | {units:15s} | {long_name}"
    # If cfgrib couldn't decode the name, dig into GRIB metadata.
    if v == "unknown" or long_name in ("?", "unknown"):
        extras = []
        for k in GRIB_KEYS:
            if k in a:
                extras.append(f"{k}={a[k]}")
        if extras:
            base += "\n      └─ " + ", ".join(extras)
    return base


def main() -> None:
    run_time = recent_run_time()
    print(f"HRRR valid: {run_time:%Y-%m-%d %H:%M UTC}\n")

    for product in ("sfc", "prs"):
        print(f"========== PRODUCT: {product.upper()} ==========")
        ds_list = load_hrrr(run_time, product=product)
        print(f"Total hypercubes: {len(ds_list)}\n")

        for i, ds in enumerate(ds_list):
            print(f"--- hypercube {i}  dims={dict(ds.sizes)} ---")
            lvl_coords = [c for c in ds.coords
                          if c not in ("time", "valid_time", "step",
                                       "latitude", "longitude", "y", "x")]
            for c in lvl_coords:
                print(f"  coord {c}: {ds[c].values}")
            for v in ds.data_vars:
                print(describe_var(ds, v))
            print()

    # ---- Sanity probes -----------------------------------------------------
    print("\n========== SANITY PROBES ==========")
    sfc_list = load_hrrr(run_time, product="sfc")

    # Every CAPE-like field across every cube
    print("\n>>> All CAPE-flavor fields:")
    for i, ds in enumerate(sfc_list):
        for v in ds.data_vars:
            units = ds[v].attrs.get("units", "")
            if "J kg" in units or "cape" in v.lower() or "cin" in v.lower():
                vals = ds[v].values
                lvl = [c for c in ds.coords if c not in
                       ("time", "valid_time", "step", "latitude", "longitude", "y", "x")]
                lvl_str = ", ".join(f"{c}={ds[c].values}" for c in lvl)
                print(f"  cube {i:2d}  {v:12s}  max={vals.max():>7.0f}  "
                      f"min={vals.min():>6.0f}  [{lvl_str}]")

    # refc sanity
    print("\n>>> Reflectivity probe:")
    for i, ds in enumerate(sfc_list):
        if "refc" in ds.data_vars:
            r = ds["refc"]
            print(f"  cube {i}  refc shape={r.shape}  units={r.attrs.get('units')}")
            print(f"            max={float(r.max()):.1f}  min={float(r.min()):.1f}")
            print(f"            pixels > 20 dBZ: {int((r > 20).sum()):,}")
            print(f"            pixels > 35 dBZ: {int((r > 35).sum()):,}")
            print(f"            has 'longitude' coord: {'longitude' in ds.coords}")
            print(f"            has 'latitude'  coord: {'latitude'  in ds.coords}")
            if "longitude" in ds.coords:
                lon = ds["longitude"].values
                lat = ds["latitude"].values
                print(f"            lon range: {lon.min():.1f} to {lon.max():.1f}")
                print(f"            lat range: {lat.min():.1f} to {lat.max():.1f}")


if __name__ == "__main__":
    main()
