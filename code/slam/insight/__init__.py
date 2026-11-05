"""Insight layer: failure prediction, pattern discovery, recreation paths and explanations.

Everything here reads what the deterministic pipeline already decided and adds analysis on top.
It never changes ``output.csv`` and never lets a model decide a status or a step.
"""
