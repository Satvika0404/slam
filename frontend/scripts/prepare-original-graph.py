"""Enhance the preserved original HTML without replacing its renderer, graph or handlers."""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
original = (root / "docs/reference/ghost-data-console.original.html").read_text(encoding="utf-8")
extension = (root / "frontend/public/reference/graph-enhancements.js").read_text(encoding="utf-8")
# Self-hosted fonts replace the original remote font request. All original graph data stays intact.
enhanced = re.sub(r'<link rel="stylesheet" href="https://fonts.googleapis.com/[^>]+>', '', original)
enhanced = enhanced.replace('<style>\n/* Layout concept:', '<link rel="stylesheet" href="/reference/graph-enhancements.css">\n<style>\n/* Layout concept:', 1)
# Load our CSS last so the original's theme rules cannot override the requested light palette.
enhanced = enhanced.replace('</body>', '<link rel="stylesheet" href="/reference/graph-enhancements.css">\n</body>')
enhanced = enhanced.replace('/* ---------- boot ---------- */', extension + '\n/* ---------- boot ---------- */', 1)
target = root / 'frontend/public/reference/ghost-data-console.html'
target.write_text(enhanced, encoding='utf-8')
