"""
Reporting: plots and a self-contained HTML summary of a solve.

Matplotlib is optional -- without it the HTML report still renders, using
inline SVG drawn directly from the data, so a headless machine can produce a
shareable result page with no extra dependencies.
"""
from __future__ import annotations

import base64
import datetime
import html
import io
import math
import os
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np


def has_matplotlib() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


def plot_sparameters(sp, pairs: Optional[Sequence[Tuple[int, int]]] = None,
                     path: Optional[str] = None, title: str = "S-parameters",
                     ylim: Tuple[float, float] = (-60.0, 2.0)):
    """Magnitude-in-dB plot; returns the Matplotlib figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pairs = pairs or [(i, j) for i in range(1, sp.n_port + 1)
                      for j in range(1, sp.n_port + 1) if i <= j]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=130)
    for i, j in pairs:
        ax.plot(sp.freq / 1e9, sp.db(i, j), label=f"S{i}{j}", lw=1.6)
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("Magnitude [dB]")
    ax.set_title(title)
    ax.set_ylim(*ylim)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(ncol=min(len(pairs), 4), fontsize=8)
    fig.tight_layout()
    if path:
        fig.savefig(path)
    return fig


def _svg_line_plot(x, series, xlabel, ylabel, width=760, height=340,
                   title="") -> str:
    """Minimal dependency-free SVG line chart."""
    if len(x) < 2:
        return "<p><em>not enough points to plot</em></p>"
    pad_l, pad_r, pad_t, pad_b = 62, 18, 28, 42
    W, H = width - pad_l - pad_r, height - pad_t - pad_b
    ys = np.concatenate([np.asarray(y) for _, y in series])
    ys = ys[np.isfinite(ys)]
    ymin, ymax = (float(ys.min()), float(ys.max())) if len(ys) else (0.0, 1.0)
    if ymax - ymin < 1e-9:
        ymax = ymin + 1.0
    pad = 0.06 * (ymax - ymin)
    ymin, ymax = ymin - pad, ymax + pad
    xmin, xmax = float(np.min(x)), float(np.max(x))

    def X(v):
        return pad_l + (v - xmin) / (xmax - xmin) * W

    def Y(v):
        return pad_t + (ymax - v) / (ymax - ymin) * H

    colors = ["#2b6cb0", "#c53030", "#2f855a", "#6b46c1", "#b7791f",
              "#0987a0", "#97266d", "#4a5568"]
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'style="font:12px system-ui,sans-serif">']
    out.append(f'<rect x="{pad_l}" y="{pad_t}" width="{W}" height="{H}" '
               f'fill="#fff" stroke="#cbd5e0"/>')
    for k in range(6):
        v = ymin + k * (ymax - ymin) / 5
        y = Y(v)
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l+W}" '
                   f'y2="{y:.1f}" stroke="#edf2f7"/>')
        out.append(f'<text x="{pad_l-6}" y="{y+4:.1f}" text-anchor="end" '
                   f'fill="#4a5568">{v:.3g}</text>')
    for k in range(6):
        v = xmin + k * (xmax - xmin) / 5
        xx = X(v)
        out.append(f'<line x1="{xx:.1f}" y1="{pad_t}" x2="{xx:.1f}" '
                   f'y2="{pad_t+H}" stroke="#edf2f7"/>')
        out.append(f'<text x="{xx:.1f}" y="{pad_t+H+16}" text-anchor="middle" '
                   f'fill="#4a5568">{v:.4g}</text>')
    for i, (label, y) in enumerate(series):
        pts = " ".join(f"{X(a):.2f},{Y(b):.2f}" for a, b in zip(x, y)
                       if np.isfinite(b))
        c = colors[i % len(colors)]
        out.append(f'<polyline fill="none" stroke="{c}" stroke-width="1.8" '
                   f'points="{pts}"/>')
        out.append(f'<text x="{pad_l+8+i*74}" y="{pad_t-8}" fill="{c}">'
                   f'{html.escape(label)}</text>')
    out.append(f'<text x="{pad_l+W/2}" y="{height-8}" text-anchor="middle" '
               f'fill="#2d3748">{html.escape(xlabel)}</text>')
    out.append(f'<text x="14" y="{pad_t+H/2}" text-anchor="middle" '
               f'fill="#2d3748" transform="rotate(-90 14 {pad_t+H/2})">'
               f'{html.escape(ylabel)}</text>')
    out.append("</svg>")
    return "".join(out)


def html_report(solution, path: str, title: Optional[str] = None) -> str:
    """Write a standalone HTML report for a solve."""
    sp = solution.sparams
    d = solution.design
    title = title or f"Aether-EM report - {d.name}"
    series = [(f"S{i}{j}", sp.db(i, j))
              for i in range(1, sp.n_port + 1)
              for j in range(1, sp.n_port + 1) if i <= j][:8]
    chart = _svg_line_plot(sp.freq / 1e9, series, "Frequency [GHz]",
                           "Magnitude [dB]") if sp and sp.n_freq > 1 else ""

    rows = []
    for c in solution.convergence:
        ds = "-" if c["delta_s"] is None else f"{c['delta_s']:.5f}"
        rows.append(f"<tr><td>{c['pass']}</td><td>{c['tets']:,}</td>"
                    f"<td>{c['dof']:,}</td><td>{ds}</td></tr>")
    conv = "".join(rows)

    ports = []
    if solution.ports:
        f0 = sorted(solution.ports)[0]
        for ps in solution.ports[f0]:
            for m in ps.modes:
                ports.append(
                    f"<tr><td>{html.escape(ps.name)}</td><td>{m.index+1}</td>"
                    f"<td>{m.kind}</td><td>{m.beta:.4g}</td>"
                    f"<td>{m.f_cut/1e9:.5g}</td>"
                    f"<td>{m.Z_wave.real:.4g} {m.Z_wave.imag:+.4g}j</td>"
                    f"<td>{m.Z_port.real:.4g} {m.Z_port.imag:+.4g}j</td></tr>")

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>
body{{font:14px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;
padding:32px;color:#1a202c;background:#f7fafc}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 10px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;
padding:18px 20px;margin-bottom:18px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 10px;border-bottom:1px solid #edf2f7;text-align:left}}
th{{background:#f7fafc;font-weight:600}} code{{background:#edf2f7;padding:1px 5px;
border-radius:4px}} .muted{{color:#718096;font-size:12px}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="muted">generated {datetime.datetime.now():%Y-%m-%d %H:%M:%S}
 &middot; solve time {solution.runtime:.2f} s</div>
<div class="card"><h2>Model</h2><pre>{html.escape(d.summary())}</pre></div>
<div class="card"><h2>S-parameters</h2>{chart}
<pre>{html.escape(sp.summary() if sp else 'no network data')}</pre></div>
<div class="card"><h2>Adaptive convergence</h2>
<table><tr><th>Pass</th><th>Tetrahedra</th><th>DOF</th><th>&Delta;S</th></tr>
{conv}</table></div>
<div class="card"><h2>Port modes</h2>
<table><tr><th>Port</th><th>Mode</th><th>Type</th><th>&beta; [rad/m]</th>
<th>f<sub>c</sub> [GHz]</th><th>Z<sub>wave</sub> [&Omega;]</th><th>Z<sub>port</sub> [&Omega;]</th></tr>
{''.join(ports)}</table></div>
</body></html>"""
    with open(path, "w") as fh:
        fh.write(doc)
    return path


__all__ = ["plot_sparameters", "html_report", "has_matplotlib"]
