"""Online chase-window slider — HRRR forecast 21Z..03Z, full domain + 6 states.

Single-pass design:
  1. Compute each forecast hour once via compute_hour().
  2. Re-render every cached result at multiple map extents (full domain
     plus per-state zooms). Re-rendering is cheap; the physics is not.

Outputs:
    docs/index.html         (full domain — landing page)
    docs/texas.html
    docs/oklahoma.html
    docs/kansas.html
    docs/nebraska.html
    docs/south_dakota.html
    docs/iowa.html

Usage:
    python chase_window_online.py
"""
from __future__ import annotations

import datetime
import io
import os

import matplotlib.pyplot as plt

from chase_beauty import compute_hour, render_hour, PLOT_EXTENT
from chase_slider import build_html
from hrrr_utils import recent_run_time


TARGET_HOURS_UTC = [21, 22, 23, 0, 1, 2, 3]   # 21Z..03Z

# Each entry produces one docs/<key>.html with that map extent.
# "index" is the landing page (full chase domain).
RENDER_EXTENTS: dict[str, list[float]] = {
    "index":        PLOT_EXTENT,
    "texas":        [-107.0, -92.5, 25.0, 36.8],
    "oklahoma":     [-103.5, -93.5, 33.0, 37.5],
    "kansas":       [-103.0, -94.0, 36.5, 40.5],
    "nebraska":     [-104.5, -94.5, 39.5, 43.5],
    "south_dakota": [-104.5, -95.5, 42.0, 46.0],
    "iowa":         [-97.5,  -89.5, 40.0, 44.0],
}


def target_valid_times(run_time: datetime.datetime) -> list[datetime.datetime]:
    chase_date = run_time.date()
    targets = []
    for h in TARGET_HOURS_UTC:
        d = chase_date if h >= 21 else chase_date + datetime.timedelta(days=1)
        targets.append(datetime.datetime.combine(d, datetime.time(h, 0)))
    return targets


def render_to_png(result, run_time, fxx, extent) -> bytes:
    fig, _ = render_hour(result, run_time=run_time, fxx=fxx, extent=extent)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def main() -> None:
    run_time = recent_run_time()
    print(f"HRRR run: {run_time:%Y-%m-%d %H:%M UTC}\n")

    targets = target_valid_times(run_time)
    print("Chase window targets (21Z–03Z):")
    for t in targets:
        print(f"  {t:%Y-%m-%d %H:%M UTC}")
    print()

    plan = []
    for valid in targets:
        delta_hours = (valid - run_time).total_seconds() / 3600
        fxx = int(round(delta_hours))
        if fxx < 0:
            print(f"  Skipping {valid:%H UTC} — already past (fxx would be {fxx})")
            continue
        if fxx > 18:
            print(f"  Warning: {valid:%H UTC} needs F{fxx:02d}; may exceed "
                  f"non-synoptic HRRR's 18h envelope.")
        plan.append((valid, fxx))

    if not plan:
        print("\nNo future hours remaining in chase window — nothing to render.")
        return

    # --- Compute pass: physics runs ONCE per hour, held in memory ----------
    print(f"\nComputing {len(plan)} hour(s) from the {run_time:%H} UTC run...\n")
    results = []
    for valid, fxx in plan:
        print(f"  -> F{fxx:02d} (valid {valid:%H UTC})...", end=" ", flush=True)
        result = compute_hour(run_time, fxx=fxx)
        d = result.diagnostics
        results.append((valid, fxx, result))
        print(f"STP max {d['stp_max']:.2f}, "
              f"CA-favorable {d['ca_favorable_pixels']:,} px")

    # --- Render pass: cheap matplotlib redraws at each extent --------------
    os.makedirs("docs", exist_ok=True)

    for name, extent in RENDER_EXTENTS.items():
        print(f"\nRendering '{name}' extent {extent}...")
        frames = []
        for valid, fxx, result in results:
            png = render_to_png(result, run_time, fxx, extent)
            frames.append({
                "fxx": fxx,
                "label": f"{valid:%H:%M UTC}  (F{fxx:02d})",
                "png": png,
                "diagnostics": result.diagnostics,
            })
        html = build_html(frames, run_time)
        out = f"docs/{name}.html"
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Saved {out}  ({len(html) / 1024 / 1024:.1f} MB)")

    print(f"\nDone. {len(RENDER_EXTENTS)} slider(s) written to docs/.")


if __name__ == "__main__":
    main()
