#!/usr/bin/env python3
"""Inline the data and the insight panels into page.template.html and write ghost-data-console.html.

Run after build_data.py and the insight stage:
  python dashboard/build_data.py
  python code/main.py --dataset dataset --insight        (writes dashboard/insight_data.json)
  python dashboard/build_page.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


page = read("page.template.html")
for marker in ("__DATA__", "__INSIGHT_DATA__", "/*__INSIGHT_CSS__*/", "/*__INSIGHT_JS__*/",
               "<!--__INSIGHT_PANELS__-->", "<!--__INSIGHT_GRAPH_PANEL__-->",
               "<!--__INSIGHT_SIM_PANEL__-->"):
    assert page.count(marker) == 1, f"template must contain {marker} exactly once"

parts = {
    "/*__INSIGHT_CSS__*/": read("insight.css"),
    "<!--__INSIGHT_PANELS__-->": read("insight_panels.html"),
    "<!--__INSIGHT_GRAPH_PANEL__-->": read("insight_graph_panel.html"),
    "<!--__INSIGHT_SIM_PANEL__-->": read("insight_sim_panel.html"),
    "/*__INSIGHT_JS__*/": read("insight.js"),
    "__INSIGHT_DATA__": read("insight_data.json"),
    "__DATA__": read("dashboard_data.json"),
}
# Data last, so a "__" sequence inside the data can never be mistaken for a marker.
for marker in ("/*__INSIGHT_CSS__*/", "<!--__INSIGHT_PANELS__-->", "<!--__INSIGHT_GRAPH_PANEL__-->",
               "<!--__INSIGHT_SIM_PANEL__-->", "/*__INSIGHT_JS__*/", "__INSIGHT_DATA__", "__DATA__"):
    page = page.replace(marker, parts[marker])
(HERE / "ghost-data-console.html").write_text(page, encoding="utf-8")
print(f"wrote {HERE / 'ghost-data-console.html'} ({len(page) / 1024:.1f} KB)")
