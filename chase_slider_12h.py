"""Render HRRR forecast hours F00..F08 as a single HTML slider.

Runs the full visibility pipeline 9 times (one per forecast hour), embeds
every PNG as base64 into a self-contained tornado_visibility.html that you
can open in any browser. Drag the slider to scrub through the forecast.

Usage:
    python chase_slider.py
"""
from __future__ import annotations

import base64
import io

import matplotlib.pyplot as plt

from chase_beauty import compute_hour, render_hour
from hrrr_utils import recent_run_time


HOURS = list(range(0, 13))  # F00..F12 inclusive (13 frames)


def render_hour_to_png_bytes(run_time, fxx: int) -> tuple[bytes, dict]:
    """Compute one forecast hour and return (PNG bytes, diagnostics)."""
    result = compute_hour(run_time, fxx=fxx)
    fig, _ = render_hour(result, run_time=run_time, fxx=fxx)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read(), result.diagnostics


def build_html(frames: list[dict], run_time) -> str:
    """Assemble the standalone HTML page with embedded base64 PNGs."""
    # Encode every frame inline.
    frames_js = []
    for f in frames:
        b64 = base64.b64encode(f["png"]).decode("ascii")
        frames_js.append({
            "fxx": f["fxx"],
            "label": f["label"],
            "src": f"data:image/png;base64,{b64}",
            "diagnostics": f["diagnostics"],
        })

    import json
    frames_json = json.dumps(frames_js)
    title = f"HRRR {run_time:%Y-%m-%d %H} UTC — Tornado Visibility Forecast"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{
    margin: 0;
    background: #1a1a1a;
    color: #ddd;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px;
    min-height: 100vh;
    box-sizing: border-box;
  }}
  h1 {{ font-size: 1.1em; margin: 0 0 12px 0; font-weight: 500; }}
  #image-wrap {{ width: 100%; max-width: 1400px; }}
  #image-wrap img {{ width: 100%; height: auto; display: block; background: #fff; border-radius: 4px; }}
  #controls {{
    width: 100%;
    max-width: 1400px;
    margin-top: 16px;
    display: flex;
    align-items: center;
    gap: 16px;
  }}
  #slider {{ flex: 1; }}
  #frame-label {{
    min-width: 180px;
    text-align: center;
    font-variant-numeric: tabular-nums;
    background: #2a2a2a;
    padding: 8px 12px;
    border-radius: 4px;
  }}
  button {{
    background: #2a2a2a; color: #ddd;
    border: 1px solid #444;
    padding: 8px 14px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.95em;
  }}
  button:hover {{ background: #3a3a3a; }}
  button.playing {{ background: #5a3a1a; border-color: #8a6a3a; }}
  #diagnostics {{
    width: 100%;
    max-width: 1400px;
    margin-top: 12px;
    font-family: ui-monospace, "SF Mono", Consolas, monospace;
    font-size: 0.85em;
    color: #999;
    background: #222;
    padding: 10px 14px;
    border-radius: 4px;
    white-space: pre;
    overflow-x: auto;
  }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="image-wrap"><img id="frame" alt=""></div>
<div id="controls">
  <button id="play">▶ Play</button>
  <input type="range" id="slider" min="0" max="{len(frames_js) - 1}" value="0" step="1">
  <div id="frame-label">F00</div>
</div>
<div id="diagnostics"></div>

<script>
const FRAMES = {frames_json};
const img = document.getElementById('frame');
const slider = document.getElementById('slider');
const label = document.getElementById('frame-label');
const diag = document.getElementById('diagnostics');
const playBtn = document.getElementById('play');

let playing = false;
let playInterval = null;

function show(i) {{
  const f = FRAMES[i];
  img.src = f.src;
  label.textContent = f.label;
  const d = f.diagnostics;
  diag.textContent =
    `MLCAPE max:  ${{d.mlcape_max.toFixed(0).padStart(6)}} J/kg     ` +
    `SRH01 max:   ${{d.srh01_max.toFixed(0).padStart(6)}} m²/s²\\n` +
    `Shear06 max: ${{d.shear06_max.toFixed(1).padStart(6)}} m/s     ` +
    `SR300 max:   ${{d.sr_kt_max.toFixed(1).padStart(6)}} kt\\n` +
    `STP range:   ${{d.stp_min.toFixed(2)}} – ${{d.stp_max.toFixed(2)}}     ` +
    `refc max:    ${{d.refc_max.toFixed(1)}} dBZ\\n` +
    `Pixels with STP > 0.5: ${{d.stp_pixels.toLocaleString()}}`;
}}

slider.addEventListener('input', () => show(+slider.value));

playBtn.addEventListener('click', () => {{
  playing = !playing;
  if (playing) {{
    playBtn.textContent = '⏸ Pause';
    playBtn.classList.add('playing');
    playInterval = setInterval(() => {{
      let v = (+slider.value + 1) % FRAMES.length;
      slider.value = v;
      show(v);
    }}, 700);
  }} else {{
    playBtn.textContent = '▶ Play';
    playBtn.classList.remove('playing');
    clearInterval(playInterval);
  }}
}});

// Keyboard arrows
document.addEventListener('keydown', (e) => {{
  if (e.key === 'ArrowRight') {{
    slider.value = Math.min(+slider.value + 1, FRAMES.length - 1);
    show(+slider.value);
  }} else if (e.key === 'ArrowLeft') {{
    slider.value = Math.max(+slider.value - 1, 0);
    show(+slider.value);
  }}
}});

show(0);
</script>
</body>
</html>
"""


def main() -> None:
    run_time = recent_run_time()
    print(f"HRRR run: {run_time:%Y-%m-%d %H:%M UTC}")
    print(f"Rendering {len(HOURS)} forecast hours: F{HOURS[0]:02d}..F{HOURS[-1]:02d}")
    print("(First run will download GRIBs — expect 5-10 min. Cached after that.)\n")

    frames = []
    for fxx in HOURS:
        print(f"  → F{fxx:02d}...", end=" ", flush=True)
        png, diagnostics = render_hour_to_png_bytes(run_time, fxx)
        frames.append({
            "fxx": fxx,
            "label": f"F{fxx:02d}  (+{fxx}h)",
            "png": png,
            "diagnostics": diagnostics,
        })
        print(f"STP max {diagnostics['stp_max']:.2f}, "
              f"{diagnostics['stp_pixels']:,} masked pixels")

    html = build_html(frames, run_time)
    out = "tornado_visibility.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Saved {out}  ({len(html) / 1024 / 1024:.1f} MB)")
    print(f"   Open in any browser; use slider, ◄ ► keys, or play button.")


if __name__ == "__main__":
    main()
