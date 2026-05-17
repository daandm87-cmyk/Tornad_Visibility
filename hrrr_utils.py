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


def recent_run_time(hours_back: int = 1) -> datetime.datetime:
    """Return a naive UTC datetime rounded down to the hour, `hours_back` ago.

    HRRR runs hourly but isn't posted instantly, so we step back a few hours
    to get a run that's reliably available.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    t = now - datetime.timedelta(hours=hours_back)
    return t.replace(minute=0, second=0, microsecond=0)


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