"""Focused probe of HRRR sfc cube 11.

Cube 11 in the earlier dump had heightAboveGround=[10, 1000] with two
'unknown' variables. This script pulls every GRIB attribute available
and shows sample values so we can confirm what those variables actually are
before using them for critical-angle interpolation.

Usage:
    python inspect_cube11.py
"""
from hrrr_utils import recent_run_time, load_hrrr


def main() -> None:
    run_time = recent_run_time()
    print(f"HRRR run: {run_time:%Y-%m-%d %H:%M UTC}\n")

    sfc_list = load_hrrr(run_time, product="sfc")
    if len(sfc_list) <= 11:
        raise RuntimeError(f"Only got {len(sfc_list)} hypercubes; cube 11 missing.")

    ds = sfc_list[11]

    print(f"=== Cube 11 ===")
    print(f"Dimensions: {dict(ds.sizes)}")
    print(f"Coordinates: {list(ds.coords)}")
    print(f"Data variables: {list(ds.data_vars)}\n")

    # Show all coords with their values
    for c in ds.coords:
        if c in ("latitude", "longitude", "y", "x"):
            continue
        print(f"Coord '{c}': {ds[c].values}")
    print()

    # For each variable, dump every attribute and sample values per level
    for v in ds.data_vars:
        print(f"--- Variable '{v}' ---")
        da = ds[v]
        print(f"  shape: {da.shape}")
        print(f"  dtype: {da.dtype}")
        print(f"  Attributes:")
        for k, val in sorted(da.attrs.items()):
            print(f"    {k:30s} = {val!r}")

        # Sample values — per height level if applicable
        if "heightAboveGround" in da.dims:
            for h_idx, h_val in enumerate(da.coords["heightAboveGround"].values):
                slc = da.isel(heightAboveGround=h_idx)
                arr = slc.values
                # Sample a center pixel and basic stats
                ny, nx = arr.shape
                center_val = float(arr[ny // 2, nx // 2])
                print(f"  height={h_val} m:")
                print(f"    min   = {float(arr.min()):>10.3f}")
                print(f"    max   = {float(arr.max()):>10.3f}")
                print(f"    mean  = {float(arr.mean()):>10.3f}")
                print(f"    center pixel = {center_val:>10.3f}")
        else:
            arr = da.values
            ny, nx = arr.shape[-2:]
            print(f"  min  = {float(arr.min()):.3f}")
            print(f"  max  = {float(arr.max()):.3f}")
            print(f"  mean = {float(arr.mean()):.3f}")
        print()

    # Cross-check: compare cube 11's 10m-level values to cube 15's u10/v10
    # — if cube 11's first variable matches u10 numerically, it's u; etc.
    print("=== Cross-check against cube 15 (known u10/v10) ===")
    if len(sfc_list) > 15 and "u10" in sfc_list[15].data_vars:
        u10_ref = sfc_list[15]["u10"].values
        v10_ref = sfc_list[15]["v10"].values
        ny, nx = u10_ref.shape
        cy, cx = ny // 2, nx // 2
        print(f"Cube 15 u10 center pixel: {u10_ref[cy, cx]:.3f}")
        print(f"Cube 15 v10 center pixel: {v10_ref[cy, cx]:.3f}")
        print(f"Cube 15 u10 max: {u10_ref.max():.3f}")
        print(f"Cube 15 v10 max: {v10_ref.max():.3f}")
        print(f"\nIf cube 11's variables at heightAboveGround=10 match these,")
        print(f"they ARE u/v wind. If they don't match, they're something else.")


if __name__ == "__main__":
    main()
