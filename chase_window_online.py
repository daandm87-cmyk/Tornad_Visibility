"""Online chase-window slider — HRRR forecast for 21Z..03Z (7 hours).

Designed for unattended runs on GitHub Actions. Same logic as
chase_window.py but covers the wider 21Z..03Z window for the online
edition, and writes output to docs/index.html so GitHub Pages can serve
it straight from the repo's docs/ folder.

Usage:
    python chase_window_online.py
"""
from __future__ import annotations

import datetime
import io
import os

import matplotlib.pyplot as plt

from chase_beauty import compute_hour, render_hour
from chase_slider import build_html
from hrrr_utils import recent_run_time


# 21Z..03Z covers peak chase + late-evening tornado activity.
# 21, 22, 23 are today's; 0, 1, 2, 3 are tomorrow's (UTC).
TARGET_HOURS_UTC = [21, 22, 23, 0, 1, 2, 3]


def target_valid_times(run_time: datetime.datetime) -> list[datetime.datetime]:
    chase_date = run_time.date()
    targets = []
    for h in TARGET_HOURS_UTC:
        d = chase_date if h >= 21 else chase_date + datetime.timedelta(days=1)
        targets.append(datetime.datetime.combine(d, datetime.time(h, 0)))
    return targets


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

    print(f"\nRendering {len(plan)} hour(s) from the {run_time:%H} UTC run...\n")

    frames = []
    for valid, fxx in plan:
        print(f"  → F{fxx:02d} (valid {valid:%H UTC})...", end=" ", flush=True)
        result = compute_hour(run_time, fxx=fxx)
        fig, _ = render_hour(result, run_time=run_time, fxx=fxx)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)

        d = result.diagnostics
        frames.append({
            "fxx": fxx,
            "label": f"{valid:%H:%M UTC}  (F{fxx:02d})",
            "png": buf.read(),
            "diagnostics": d,
        })
        print(f"STP max {d['stp_max']:.2f}, "
              f"CA-favorable {d['ca_favorable_pixels']:,} px")

    html = build_html(frames, run_time)

    # Write to docs/index.html so GitHub Pages serves it at the site root.
    os.makedirs("docs", exist_ok=True)
    out = "docs/index.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Saved {out}  ({len(html) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
