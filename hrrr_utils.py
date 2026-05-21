"""Shared helpers for HRRR-based storm chase analysis."""
from __future__ import annotations

import datetime
import sys
import warnings
from typing import Iterable

from herbie import Herbie

# Force UTF-8 stdio on Windows so Herbie's emoji prints don't crash
# when output is redirected to a file (cp1252 default).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, Exception):
        pass

# HRRR loading produces a lot of harmless noise. Silence it once, here.
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


def recent_run_time(hours_back: int = 3) -> datetime.datetime:
    """Return a naive UTC datetime rounded down to the hour, `hours_back` ago.

    HRRR runs hourly but isn't posted instantly, so we step back a few hours
    to get a run that's reliably available.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    t = now - datetime.timedelta(hours=hours_back)
    return t.replace(minute=0, second=0, microsecond=0)


def latest_complete_run(max_fxx_needed: int, product: str = "sfc",
                        search_hours: int = 8) -> datetime.datetime:
    """Find the most recent HRRR run whose `max_fxx_needed` file is on AWS.

    NOAA does not publish an explicit "run complete" flag, so we probe Herbie
    (which does a fast existence check, no download) starting from the current
    hour and walking backward up to `search_hours`. Returns the first run that
    has its highest-needed forecast hour fully uploaded.

    Raises RuntimeError if no complete run is found within the search window.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    base = now.replace(minute=0, second=0, microsecond=0)

    print(f"Probing AWS for latest complete HRRR run covering F{max_fxx_needed:02d}...")
    for hb in range(0, search_hours + 1):
        candidate = base - datetime.timedelta(hours=hb)
        try:
            H = Herbie(date=candidate, model="hrrr", product=product,
                       fxx=max_fxx_needed, verbose=False)
            # H.grib is the resolved source path/URL when found, None otherwise.
            if getattr(H, "grib", None) is not None:
                print(f"  ✓ {candidate:%Y-%m-%d %H:%M UTC} run has F{max_fxx_needed:02d} "
                      f"available (probed {hb + 1} run(s)).")
                return candidate
        except Exception:
            pass
        # Quietly continue — this run's max fxx isn't up yet.
    raise RuntimeError(
        f"No complete HRRR run found in the last {search_hours} hours that "
        f"has F{max_fxx_needed:02d} uploaded. Try again in a few minutes."
    )


def load_hrrr(run_time: datetime.datetime, product: str = "sfc",
              fxx: int = 0, save_dir: str = "./hrrr_data") -> list:
    """Download (if needed) and load a HRRR run as a list of xarray datasets."""
    H = Herbie(date=run_time, model="hrrr", product=product, fxx=fxx, save_dir=save_dir)
    ds = H.xarray()
    return ds if isinstance(ds, list) else [ds]


def find_dataset_with(datasets: Iterable, *required_vars: str,
                      require_coord: str | None = None):
    """Return the first dataset containing all `required_vars` (+ optional coord)."""
    for ds in datasets:
        if all(v in ds.data_vars for v in required_vars):
            if require_coord is None or require_coord in ds.coords:
                return ds
    return None
