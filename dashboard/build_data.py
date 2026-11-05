#!/usr/bin/env python3
"""Build dashboard/dashboard_data.json from the participant-facing files in dataset/.

Only dataset/ is read (no organizer-only files, no golden labels). Deterministic: no wall-clock,
no randomness. Run from anywhere:  python dashboard/build_data.py
SQL evidence is loaded into an in-memory SQLite database behind an allow-list authorizer.
"""
from __future__ import annotations

import csv
import glob
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DS = ROOT / "dataset"
OUT = Path(__file__).resolve().parent / "dashboard_data.json"

MONTHS = [f"2026-{m:02d}" for m in range(1, 10)]  # Jan..Sep are complete months; Oct holds 3 events
DESTRUCTIVE = {"DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"}


# --------------------------------------------------------------------------- statistics helpers
def wilson(bad: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = bad / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def ols_forecast(y: list[float], horizon: int = 3, level: float = 0.8) -> dict:
    n = len(y)
    x = np.arange(n, dtype=float)
    yy = np.asarray(y, dtype=float)
    if n < 4 or float(np.ptp(yy)) == 0.0:
        base = float(yy.mean()) if n else 0.0
        return {"slope": 0.0, "p": 1.0, "fc": [{"h": h, "y": base, "lo": base, "hi": base} for h in range(1, horizon + 1)]}
    res = stats.linregress(x, yy)
    fit = res.intercept + res.slope * x
    s = math.sqrt(float(((yy - fit) ** 2).sum()) / (n - 2))
    xbar = x.mean()
    sxx = float(((x - xbar) ** 2).sum())
    tcrit = float(stats.t.ppf(0.5 + level / 2, n - 2))
    fc = []
    for h in range(1, horizon + 1):
        x0 = n - 1 + h
        yhat = res.intercept + res.slope * x0
        pi = tcrit * s * math.sqrt(1 + 1 / n + (x0 - xbar) ** 2 / sxx)
        fc.append({"h": h, "y": round(max(0.0, yhat), 3), "lo": round(max(0.0, yhat - pi), 3), "hi": round(max(0.0, yhat + pi), 3)})
    return {"slope": round(float(res.slope), 4), "p": round(float(res.pvalue), 4), "fc": fc,
            "fit": [round(float(v), 3) for v in fit]}


def trend_label(slope: float, p: float) -> str:
    if p < 0.10 and slope > 0:
        return "Rising"
    if p < 0.10 and slope < 0:
        return "Falling"
    return "Stable"


def confidence(n: int) -> str:
    return "High" if n >= 100 else ("Medium" if n >= 30 else "Low")


# --------------------------------------------------------------------------- load participant data
act = pd.read_csv(DS / "system_activity.csv")
act["t"] = pd.to_datetime(act["event_time"], utc=True)
act["month"] = act["t"].dt.strftime("%Y-%m")
act["bad"] = (act["reported_result"] != "SUCCESS").astype(int)
rules = list(csv.DictReader(open(DS / "deletion_rules.csv", encoding="utf-8")))
manifest = {r["file_path"].split("/")[-1]: r for r in csv.DictReader(open(DS / "evidence_files.csv", encoding="utf-8"))}
audit_log = pd.read_csv(DS / "user_audit_log.csv")
requests_n = sum(1 for _ in csv.DictReader(open(DS / "deletion_requests.csv", encoding="utf-8")))
AS_OF = max(pd.Timestamp(r["captured_at"]) for r in manifest.values())  # end of the evidence window
AS_OF = max(AS_OF, act["t"].max())


# --------------------------------------------------------------------------- SQL evidence (sandboxed)
_ALLOWED = {sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
            sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_PRAGMA, sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_REINDEX}  # REINDEX is issued internally while building the evidence indexes


def _auth(action, arg1=None, *_):
    if action == sqlite3.SQLITE_UPDATE and arg1 == "sqlite_master":  # SQLite's own schema bookkeeping for CREATE TABLE
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


def load_sql(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.set_authorizer(_auth)
    con.executescript(Path(path).read_text(encoding="utf-8"))
    con.set_authorizer(None)
    con.row_factory = sqlite3.Row
    return con


INVENTORY_TABLES = {
    "customer_profiles": "account_service", "customer_search_documents": "search_service",
    "customer_analytics_profiles": "analytics_platform", "support_records": "support_platform",
    "customer_exports": "export_service", "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service", "security_audit_records": "security_service",
    "customer_profiles_primary": "account_service", "customer_profiles_failover_replica": "account_service",
    "search_documents_primary": "search_service",
}
IDENT_KEYS = {"email", "phone", "email_hash", "name", "full_name", "display_name", "owner_email", "owner_phone",
              "customer_email", "requester_email", "requester_name", "requester_phone", "uploaded_by", "subject_selector"}


def has_identifier(fields: dict) -> bool:
    for k, v in fields.items():
        if v in (None, "", 0) or isinstance(v, (dict, list, bool)):
            continue
        if k in IDENT_KEYS or (isinstance(v, str) and "@" in v):
            return True
    return False


def as_bool(v) -> bool:
    return v in (1, True, "1", "true", "True")


records: dict[str, dict] = {}          # latest state per resource across primary / inventory tables
replica_series: list[dict] = []         # one entry per (snapshot, replica table)
snapshot_meta: list[dict] = []
for path in sorted(glob.glob(str(DS / "evidence" / "databases" / "*.sql"))):
    name = Path(path).name
    man = manifest[name]
    fid, cap = man["file_id"], pd.Timestamp(man["captured_at"])
    con = load_sql(path)
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    snapshot_meta.append({"file_id": fid, "name": name, "captured_at": man["captured_at"], "tables": len(tables)})
    prim_rows: dict[str, dict] = {}
    if "customer_data_primary" in tables:
        for r in con.execute("select * from customer_data_primary"):
            f = json.loads(r["record_json"])
            prim_rows[r["resource_id"]] = {"raw": r["record_json"], "upd": r["updated_at"], "sys": r["origin_system"], "coll": r["collection_name"], "f": f}
            rec = {"rid": r["resource_id"], "system": r["origin_system"], "coll": r["collection_name"], "f": f, "cap": cap, "file": fid}
            if r["resource_id"] not in records or records[r["resource_id"]]["cap"] <= cap:
                records[r["resource_id"]] = rec
    for t in tables:
        if t.startswith("customer_data_") and t != "customer_data_primary" and ("replica" in t):
            rep = {}
            for r in con.execute(f"select * from {t}"):
                rep[r["resource_id"]] = {"raw": r["record_json"], "upd": r["updated_at"], "sys": r["origin_system"], "f": json.loads(r["record_json"])}
            ghosts = sorted(set(rep) - set(prim_rows))
            missing = sorted(set(prim_rows) - set(rep))
            diverged = sorted(k for k in rep if k in prim_rows and rep[k]["raw"] != prim_rows[k]["raw"])
            replica_series.append({
                "file_id": fid, "captured_at": man["captured_at"], "table": t, "topology": re.sub(r"^customer_data_", "", t),
                "primary_rows": len(prim_rows), "replica_rows": len(rep), "ghost_rows": len(ghosts), "missing_rows": len(missing),
                "diverged_rows": len(diverged),
                "ghost_with_identifiers": sum(1 for g in ghosts if has_identifier(rep[g]["f"])),
                "ghost_systems": sorted({rep[g]["sys"] for g in ghosts}),
            })
    for t in tables:
        if t in INVENTORY_TABLES:
            for r in con.execute(f"select * from {t}"):
                f = {k: r[k] for k in r.keys()}
                rid = f["resource_id"]
                rec = {"rid": rid, "system": INVENTORY_TABLES[t], "coll": t, "f": f, "cap": cap, "file": fid}
                if t.endswith("replica") or t == "customer_profiles_failover_replica":
                    continue
                if rid not in records or records[rid]["cap"] <= cap:
                    records[rid] = rec

by_system: dict[str, list[dict]] = defaultdict(list)
for rec in records.values():
    by_system[rec["system"]].append(rec)
snap_stats = {s: {"resources": len(v), "with_identifiers": sum(1 for r in v if has_identifier(r["f"]))} for s, v in by_system.items()}


# --------------------------------------------------------------------------- TAB 1: error patterns
def monthly(mask, kind: str) -> list[dict]:
    sub = act[mask]
    out = []
    for m in MONTHS:
        s = sub[sub["month"] == m]
        out.append({"m": m, "n": int(len(s)), "c": int(s["bad"].sum()) if kind == "failure" else int(len(s))})
    return out


claim_re = r"reported the requested operation as completed|could not confirm the final state|stopped after the target system returned an error"
PATTERNS = [
    dict(id="P01", name="Primary profile deletion not confirmed", group="Deletion outcome", sig="DELETE_RECORD → account_service", rule="rule_01", kind="failure",
         mask=(act.event_type == "DELETE_RECORD") & (act.target_system == "account_service"),
         note="Half of the deletion calls against the account store return FAILED or PARTIAL, so the profile and its secondary identifiers can survive."),
    dict(id="P02", name="Search-index deletion not confirmed", group="Deletion outcome", sig="DELETE_RECORD → search_service", rule="rule_03", kind="failure",
         mask=(act.event_type == "DELETE_RECORD") & (act.target_system == "search_service"),
         note="Nine in ten index deletions fail. Index entries are rebuilt from the account store, so they persist and re-appear."),
    dict(id="P03", name="Support redaction and attachment deletion failing", group="Deletion outcome", sig="REDACT / DELETE → support_platform", rule="rule_05, rule_06", kind="failure",
         mask=(act.target_system == "support_platform") & act.event_type.isin(["REDACT_RECORD", "DELETE_RECORD"]),
         note="Messages that must be redacted and attachments that must be deleted stay in place for roughly three in four requests."),
    dict(id="P04", name="Export deletion failing", group="Deletion outcome", sig="DELETE_RECORD → export_service", rule="rule_09", kind="failure",
         mask=(act.event_type == "DELETE_RECORD") & (act.target_system == "export_service"),
         note="Almost every export deletion fails, leaving downloadable archives of personal data."),
    dict(id="P05", name="Analytics anonymization incomplete", group="Deletion outcome", sig="ANONYMIZE_RECORD → analytics_platform", rule="rule_07, rule_08", kind="failure",
         mask=(act.event_type == "ANONYMIZE_RECORD") & (act.target_system == "analytics_platform"),
         note="Profiles and telemetry remain attributable to a user in about one case in three."),
    dict(id="P06", name="Replication checkpoint failures", group="Replication", sig="SYNC_RECORD → account_replication_cluster", rule="rule_01", kind="failure",
         mask=(act.event_type == "SYNC_RECORD") & (act.target_system == "account_replication_cluster"),
         note="Replica checkpoints fail or stall, which is where rows that no longer exist in the primary come from."),
    dict(id="P07", name="Tombstone redaction failing", group="Deletion outcome", sig="REDACT_RECORD → identity_service", rule="rule_15", kind="failure",
         mask=(act.event_type == "REDACT_RECORD") & (act.target_system == "identity_service"),
         note="Account tombstones keep direct identifiers when the redaction does not finish."),
    dict(id="P08", name="Upstream write failures", group="Upstream writes", sig="UPDATE / INDEX / SYNC / REFRESH / EMAIL / EXPORT / RETAIN", rule="—", kind="failure",
         mask=act.event_type.isin(["UPDATE_RECORD", "INDEX_RECORD", "REFRESH_CACHE", "SEND_EMAIL", "CREATE_EXPORT", "RETAIN_RECORD"]) | ((act.event_type == "SYNC_RECORD") & (act.target_system == "analytics_platform")),
         note="Partial or failed writes leave copies that disagree with the source, the root cause of most later drift."),
    dict(id="P09", name="Data flow confirmed still enabled", group="Recreation risk", sig="CHECK_DATA_FLOW → integration_service", rule="allowed op: DISABLE_DATA_FLOW", kind="occurrence",
         mask=act.event_type == "CHECK_DATA_FLOW",
         note="Connector checks that found the flow running. Each one is a path that can copy deleted data back."),
    dict(id="P10", name="Connector repopulated a downstream index", group="Recreation risk", sig="SYNC_RECORD integration_service → search_service", rule="allowed op: DISABLE_DATA_FLOW", kind="occurrence",
         mask=(act.source_system == "integration_service") & (act.event_type == "SYNC_RECORD"),
         note="An active connector wrote search entries after the source was handled."),
    dict(id="P11", name="Archive confirmed restorable", group="Recreation risk", sig="CHECK_RESTORE_ACCESS → backup_service", rule="rule_14", kind="occurrence",
         mask=act.event_type == "CHECK_RESTORE_ACCESS",
         note="Backups that can still be restored. Rule 14 only allows retention when restore access can be blocked."),
    dict(id="P12", name="Completion claimed without a confirmed state", group="Claim integrity", sig="worker reports completed / stopped / unconfirmed", rule="—", kind="occurrence",
         mask=act.details.str.contains(claim_re, regex=True, na=False),
         note="The worker reports completion, or stops on an error, without a final state from the target system. Treat as a claim."),
]

patterns_out = []
for P in PATTERNS:
    sub = act[P["mask"]]
    n = int(len(sub))
    bad = int(sub["bad"].sum()) if P["kind"] == "failure" else n
    ser = monthly(P["mask"], P["kind"])
    y = [s["c"] for s in ser]
    fcast = ols_forecast(y)
    lo, hi = wilson(bad, n) if P["kind"] == "failure" else (None, None)
    patterns_out.append({
        "id": P["id"], "name": P["name"], "group": P["group"], "signature": P["sig"], "rule": P["rule"], "kind": P["kind"], "note": P["note"],
        "n": n, "count": bad, "rate": round(bad / n, 4) if P["kind"] == "failure" and n else None,
        "ci": [round(lo, 4), round(hi, 4)] if lo is not None else None,
        "series": ser, "slope": fcast["slope"], "p": fcast["p"], "trend": trend_label(fcast["slope"], fcast["p"]),
        "forecast": fcast["fc"], "fit": fcast.get("fit"), "confidence": confidence(n),
        "examples": (sub[sub.bad == 1] if P["kind"] == "failure" else sub).sort_values("t").tail(3).activity_id.tolist(),
    })

# P13: delete reported SUCCESS, then the same resource is written again
writes = {"UPDATE_RECORD", "INDEX_RECORD", "SYNC_RECORD", "REFRESH_CACHE", "RESTORE_BACKUP", "CREATE_EXPORT", "SEND_EMAIL"}
reborn = []
for rid, grp in act.sort_values("t").groupby("resource_id"):
    seen = None
    for _, r in grp.iterrows():
        if r.event_type == "DELETE_RECORD" and r.reported_result == "SUCCESS":
            seen = r
        elif seen is not None and r.event_type in writes:
            reborn.append({"rid": rid, "month": seen.month, "gap_s": int((r.t - seen.t).total_seconds()), "via": f"{r.source_system} {r.event_type}"})
            break
gaps = [x["gap_s"] for x in reborn]
ser = [{"m": m, "n": sum(1 for x in reborn if x["month"] == m), "c": sum(1 for x in reborn if x["month"] == m)} for m in MONTHS]
fc = ols_forecast([s["c"] for s in ser])
patterns_out.append({
    "id": "P13", "name": "Record written again after a successful delete", "group": "Recreation risk",
    "signature": "DELETE_RECORD SUCCESS, then a write to the same resource_id", "rule": "§6.5 recreation paths", "kind": "occurrence",
    "note": f"Replication or sync wrote the resource again a median {int(np.median(gaps) // 60) if gaps else 0} minutes after the delete was reported as done.",
    "n": len(reborn), "count": len(reborn), "rate": None, "ci": None, "series": ser, "slope": fc["slope"], "p": fc["p"],
    "trend": trend_label(fc["slope"], fc["p"]), "forecast": fc["fc"], "fit": fc.get("fit"), "confidence": confidence(len(reborn)),
    "examples": act[act.resource_id.isin([x["rid"] for x in reborn]) & (act.event_type == "SYNC_RECORD")].sort_values("t").tail(3).activity_id.tolist(),
})

# P14: replica ghost rows from SQL evidence
rs = sorted(replica_series, key=lambda r: r["captured_at"])
ghost_months = defaultdict(lambda: [0, 0])
for r in rs:
    m = r["captured_at"][:7]
    ghost_months[m][0] += 1
    ghost_months[m][1] += r["ghost_rows"]
ser = [{"m": m, "n": ghost_months[m][0], "c": ghost_months[m][1]} for m in MONTHS]
nonzero = [s for s in ser if s["n"] > 0]
fc = ols_forecast([s["c"] / s["n"] for s in nonzero]) if len(nonzero) >= 4 else {"slope": 0, "p": 1, "fc": [], "fit": None}
snaps_with_ghost = sum(1 for r in rs if r["ghost_rows"] > 0)
patterns_out.append({
    "id": "P14", "name": "Replica holds rows the primary no longer has", "group": "Replication",
    "signature": "replica table minus primary table, same snapshot", "rule": "§6.6 replication drift", "kind": "snapshot",
    "note": f"{snaps_with_ghost} of {len(rs)} replica tables in the SQL evidence hold at least one row that is absent from their primary.",
    "n": len(rs), "count": sum(r["ghost_rows"] for r in rs), "rate": round(snaps_with_ghost / len(rs), 4) if rs else None,
    "ci": [round(v, 4) for v in wilson(snaps_with_ghost, len(rs))] if rs else None,
    "series": ser, "slope": fc["slope"], "p": fc["p"], "trend": trend_label(fc["slope"], fc["p"]),
    "forecast": fc["fc"], "fit": None, "confidence": confidence(len(rs) * 3),
    "examples": [r["file_id"] for r in rs if r["ghost_rows"]][-3:],
})

# overall rate trend (all events, complete months)
rate_ser = []
for m in MONTHS:
    s = act[act.month == m]
    rate_ser.append({"m": m, "n": int(len(s)), "bad": int(s.bad.sum()), "rate": round(float(s.bad.mean()), 4)})
rate_fc = ols_forecast([r["rate"] for r in rate_ser])
count_fc = ols_forecast([r["bad"] for r in rate_ser])
ctrl = act[act.event_type.isin(DESTRUCTIVE)]
ctrl_ser = []
for m in MONTHS:
    s = ctrl[ctrl.month == m]
    ctrl_ser.append({"m": m, "n": int(len(s)), "bad": int(s.bad.sum()), "rate": round(float(s.bad.mean()), 4)})
ctrl_fc = ols_forecast([r["rate"] for r in ctrl_ser])

# heatmap: controlled operations by system and month
HEAT_SYS = ["account_service", "search_service", "support_platform", "analytics_platform", "export_service", "account_replication_cluster", "identity_service"]
heat_mask = act.event_type.isin(DESTRUCTIVE) | ((act.event_type == "SYNC_RECORD") & (act.target_system == "account_replication_cluster"))
heat = []
for s in HEAT_SYS:
    row = []
    for m in MONTHS:
        sub = act[heat_mask & (act.target_system == s) & (act.month == m)]
        row.append([int(len(sub)), int(sub.bad.sum())])
    heat.append({"system": s, "cells": row})

# per-system ranking
sys_rank = []
for s, g in act.groupby("target_system"):
    n, bad = int(len(g)), int(g.bad.sum())
    last3 = g[g.month.isin(["2026-07", "2026-08", "2026-09"])]
    ms = [int(g[g.month == m].bad.sum()) for m in MONTHS]
    f1 = ols_forecast(ms, horizon=1)["fc"][0]
    lo, hi = wilson(bad, n)
    sys_rank.append({"system": s, "n": n, "bad": bad, "rate": round(bad / n, 4), "ci": [round(lo, 4), round(hi, 4)],
                     "recent_avg_bad": round(int(last3.bad.sum()) / 3, 2), "next_bad": f1["y"], "next_lo": f1["lo"], "next_hi": f1["hi"]})
sys_rank.sort(key=lambda r: (-r["rate"], -r["n"]))

# predictor lookup (event type x target system)
cls_rate = {"destructive": float(ctrl.bad.mean()), "other": float(act[~act.event_type.isin(DESTRUCTIVE)].bad.mean())}
pred_tbl = []
for (et, ts), g in act.groupby(["event_type", "target_system"]):
    if len(g) < 10:
        continue
    last3 = g[g.month.isin(["2026-07", "2026-08", "2026-09"])]
    pred_tbl.append({"op": et, "system": ts, "n": int(len(g)), "bad": int(g.bad.sum()), "n3": int(len(last3)), "bad3": int(last3.bad.sum()),
                     "cls": "destructive" if et in DESTRUCTIVE else "other"})
pred_tbl.sort(key=lambda r: (-r["n"], r["op"], r["system"]))

drift_rows = [{k: r[k] for k in ("file_id", "captured_at", "topology", "primary_rows", "replica_rows", "ghost_rows", "missing_rows", "diverged_rows", "ghost_with_identifiers")} for r in rs]

# --------------------------------------------------------------------------- TAB 2: retention conflicts
def latest_by(coll: str) -> list[dict]:
    return [r for r in records.values() if r["coll"] == coll]


def ev_ids(items: list[dict], k: int = 4) -> list[str]:
    seen = sorted({r["file"] for r in items}, key=lambda f: int(f.split("_")[1]))
    return seen[:k]


exports = latest_by("customer_export_jobs")
exp_expired = [r for r in exports if as_bool(r["f"].get("download_available")) and pd.Timestamp(r["f"]["expires_at"]) < AS_OF]
backups = latest_by("backup_catalog") + latest_by("backup_restore_entries")
bk_open = [r for r in backups if as_bool(r["f"].get("restore_allowed"))]
conns = latest_by("connector_configurations") + latest_by("connector_subscriptions")
cn_on = [r for r in conns if as_bool(r["f"].get("enabled"))]
tombs = latest_by("deleted_customer_references")
tomb_ident = [r for r in tombs if any(r["f"].get(k) for k in ("name", "email", "phone", "email_hash"))]
audits = latest_by("security_audit_records")
ret_years = Counter(pd.Timestamp(r["f"]["retention_until"]).year for r in audits)
legal = latest_by("retained_order_records")
legal_years = Counter(pd.Timestamp(r["f"]["retained_until"]).year for r in legal)
ghost_total = sum(r["ghost_rows"] for r in rs)
ghost_ident = sum(r["ghost_with_identifiers"] for r in rs)

# destructive operations that never reached SUCCESS for the same resource
ops = act[act.event_type.isin(DESTRUCTIVE)].sort_values("t")
unresolved = Counter()
for rid, g in ops.groupby("resource_id"):
    if (g.reported_result == "SUCCESS").any():
        continue
    unresolved[g.iloc[-1].target_system] += 1
unresolved_total = sum(unresolved.values())

# data flows / restore checks without a later disable / block (activity)
flow_state = {}
for _, r in act[act.event_type.isin(["CHECK_DATA_FLOW", "DISABLE_DATA_FLOW"])].sort_values("t").iterrows():
    flow_state[r.resource_id] = r.event_type
flows_open_act = sum(1 for v in flow_state.values() if v == "CHECK_DATA_FLOW")
bk_state = {}
for _, r in act[act.event_type.isin(["CHECK_RESTORE_ACCESS", "BLOCK_RESTORE"])].sort_values("t").iterrows():
    bk_state[r.resource_id] = r.event_type
backups_open_act = sum(1 for v in bk_state.values() if v == "CHECK_RESTORE_ACCESS")

# superseded identifiers
audit_log["t"] = pd.to_datetime(audit_log["event_time"], utc=True)
audit_log["age"] = (AS_OF - audit_log["t"]).dt.days
ident_fields = []
for fld, g in audit_log.groupby("field_name"):
    ident_fields.append({"field": fld, "changes": int(len(g)), "over_365": int((g.age > 365).sum()), "users": int(g.user_id.nunique())})
ident_fields.sort(key=lambda r: -r["changes"])

# aging explorer (30-day bins) for exports, cache entries and search-index entries without a confirmed delete
confirmed = set(act[(act.event_type == "DELETE_RECORD") & (act.reported_result == "SUCCESS")].resource_id)
BINS = [(0, 30), (30, 60), (60, 90), (90, 120), (120, 150), (150, 180), (180, 210), (210, 240), (240, 270)]
aging = []
for label, et, tgt in (("User exports", "CREATE_EXPORT", "object_store"), ("Cache entries", "REFRESH_CACHE", "cache_service"), ("Search-index entries", "INDEX_RECORD", "search_service")):
    sub = act[(act.event_type == et) & (act.target_system == tgt) & (~act.resource_id.isin(confirmed))].copy()
    sub["age"] = (AS_OF - sub["t"]).dt.days
    counts = [int(((sub.age >= lo) & (sub.age < hi)).sum()) for lo, hi in BINS]
    aging.append({"label": label, "system": tgt, "total": int(len(sub)), "bins": counts})

# legal register in the PDF
legal_register = []
try:
    import pypdf
    reader = pypdf.PdfReader(str(DS / "evidence" / "documents" / "legal_retention_register_20260529.pdf"))
    txt = "\n".join(p.extract_text() for p in reader.pages)
    for m in re.finditer(r"(ORD-\d+) \| (user_\d+) \| ([A-Za-z ]+) \| ([\d]+ \w+ \d{4}) \|[^|]*\| Retain until (\d+ \w+ \d{4})", txt):
        legal_register.append({"order": m.group(1), "user": m.group(2), "kind": m.group(3).strip(), "retain_until": m.group(5)})
except Exception:  # PDF parsing is optional
    legal_register = []
legal_file = manifest["legal_retention_register_20260529.pdf"]["file_id"]
sec_file = manifest["security_retention_extract.pdf"]["file_id"]

register = [
    dict(id="C01", cat="Exports", title="Exports past expiry, last seen downloadable", n=len(exp_expired), unit="export jobs", sev="High", rule="rule_09",
         why="The export window has closed (expires_at is before the end of the evidence window), so nothing needs the archive.",
         conflict="Each was still marked download_available at its last snapshot. A link that outlives its expiry keeps a full copy outside any deletion run.",
         action="DELETE_RECORD on the export job and its object", ev=ev_ids(exp_expired)),
    dict(id="C02", cat="Backups", title="Archives that can still be restored", n=len(bk_open), unit="backup entries", sev="High", rule="rule_14",
         why="Backups are kept only if restore access can be blocked, and these allow restore.",
         conflict="A restore would bring back profile, search and analytics rows that were already deleted.",
         action="BLOCK_RESTORE, then VERIFY_RESTORE_BLOCKED", ev=ev_ids(bk_open)),
    dict(id="C03", cat="Data flows", title="Continuous-sync connectors still enabled", n=len(cn_on), unit="connectors", sev="High", rule="allowed op",
         why="Once the source record is deleted the connector has no legitimate reason to run.",
         conflict="An enabled connector copies customer events to the warehouse and search again after cleanup.",
         action="DISABLE_DATA_FLOW before any record is changed", ev=ev_ids(cn_on)),
    dict(id="C04", cat="Replicas", title="Rows present only in a replica", n=ghost_total, unit="replica rows", sev="High", rule="rule_01",
         why="The primary no longer holds these rows, so the replica is the only copy left.",
         conflict=f"{ghost_ident} of these carry direct identifiers and will be served to readers and reports.",
         action="DELETE_RECORD on the replica row, then re-check drift", ev=sorted({r["file_id"] for r in rs if r["ghost_rows"]}, key=lambda f: int(f.split("_")[1]))[:4]),
    dict(id="C05", cat="Deletion runs", title="Destructive operations that never reached SUCCESS", n=unresolved_total, unit="resources", sev="High", rule="rules 01–09",
         why="The run was reported as FAILED or PARTIAL and no later attempt on the same resource succeeded.",
         conflict="These stay in scope for every later audit and for any restore or sync that touches the same source.",
         action="Re-run the policy action, then verify the resulting state", ev=ops[ops.bad == 1].sort_values("t").tail(3).activity_id.tolist()),
    dict(id="C06", cat="Tombstones", title="Tombstones that still carry direct identifiers", n=len(tomb_ident), unit="tombstones", sev="Medium", rule="rule_15",
         why="A tombstone only needs the stable user reference.",
         conflict="Names, emails or phones left on a tombstone are directly identifying data with no purpose.",
         action="REDACT_RECORD, keep the user reference", ev=ev_ids(tomb_ident)),
    dict(id="C07", cat="Identifiers", title="Superseded email, hash and phone values", n=int(sum(f["changes"] for f in ident_fields)), unit="old values", sev="Medium", rule="matching",
         why=f"The person replaced these values; {int(sum(f['over_365'] for f in ident_fields))} phone numbers were replaced over 12 months before the evidence window closed.",
         conflict="Older systems keyed to an old email or phone are missed when a request arrives under the current one.",
         action="Keep in the identity map for lookup, remove from live stores", ev=audit_log.sort_values("t").head(3).audit_id.tolist()),
    dict(id="C08", cat="Retention", title="Audit records with a defined retention end", n=len(audits), unit="audit records", sev="Low", rule="rule_12",
         why=f"Retention runs to {min(ret_years)}–{max(ret_years)}; after that date the record is no longer required.",
         conflict="Keeping a record past its date turns a lawful retention into unnecessary storage of personal data.",
         action="Schedule release at retention_until", ev=ev_ids(audits)),
    dict(id="C09", cat="Retention", title="Order records held for disputes and tax", n=len(legal) + len(legal_register), unit="order records", sev="Low", rule="rule_13",
         why="Held under an active legal hold or tax rule; the register states a retain-until date.",
         conflict="The hold date has to be tracked: deleting early breaches the hold, keeping late breaches minimization.",
         action="RETAIN, review at the retain-until date", ev=[legal_file] + ev_ids(legal, 3)),
]
register_n = {r["id"]: r["n"] for r in register}

# --------------------------------------------------------------------------- TAB 3: system graph (NetworkX)
SYSTEMS = {
    # id: (label, tier, data category, rule ids, policy action)
    "profile_service": ("Profile service", "source", "Profile preferences", "—", "NONE"),
    "account_service": ("Account service", "store", "USER_PROFILE, SECONDARY_IDENTIFIER", "rule_01, rule_02", "DELETE"),
    "account_replication_cluster": ("Account replication cluster", "replica", "USER_PROFILE (replica)", "rule_01", "DELETE"),
    "account_failover_replica": ("Account failover replica", "replica", "USER_PROFILE (replica)", "rule_01", "DELETE"),
    "search_service": ("Search service", "copy", "SEARCH_INDEX_ENTRY", "rule_03", "DELETE"),
    "cache_service": ("Cache service", "copy", "CACHE_ENTRY", "rule_04", "DELETE"),
    "analytics_platform": ("Analytics platform", "copy", "ANALYTICS_PROFILE, PRODUCT_TELEMETRY", "rule_07, rule_08", "ANONYMIZE"),
    "notification_service": ("Notification service", "source", "Outbound notifications", "—", "NONE"),
    "email_delivery_service": ("Email delivery service", "copy", "EMAIL_DELIVERY_LOG", "rule_11", "REDACT"),
    "support_platform": ("Support platform", "store", "SUPPORT_MESSAGE, SUPPORT_ATTACHMENT", "rule_05, rule_06", "REDACT"),
    "object_storage": ("Attachment object storage", "copy", "SUPPORT_ATTACHMENT (files)", "rule_06", "DELETE"),
    "export_service": ("Export service", "store", "USER_EXPORT", "rule_09", "DELETE"),
    "object_store": ("Export object store", "copy", "USER_EXPORT (files)", "rule_09", "DELETE"),
    "marketing_platform": ("Marketing platform", "store", "MARKETING_PROFILE", "rule_10", "DELETE"),
    "security_service": ("Security service", "source", "SECURITY_AUDIT_LOG (source)", "rule_12", "RETAIN"),
    "archive_service": ("Archive service", "retained", "SECURITY_AUDIT_LOG", "rule_12", "RETAIN"),
    "legal_service": ("Legal service", "retained", "LEGAL_HOLD_RECORD", "rule_13", "RETAIN"),
    "backup_service": ("Backup service", "retained", "BACKUP_ARCHIVE", "rule_14", "RETAIN"),
    "identity_service": ("Identity service", "store", "ACCOUNT_TOMBSTONE", "rule_15", "REDACT"),
    "integration_service": ("Integration service", "flow", "Data flows (connectors)", "allowed op", "DISABLE"),
    "privacy_intake": ("Privacy intake", "source", "Request intake", "—", "NONE"),
    "privacy_case_management": ("Privacy case management", "store", "Request cases", "—", "NONE"),
}
OBSERVED = [
    ("profile_service", "account_service", "UPDATE_RECORD", False),
    ("account_service", "search_service", "INDEX_RECORD", False),
    ("account_service", "analytics_platform", "SYNC_RECORD", False),
    ("account_service", "cache_service", "REFRESH_CACHE", False),
    ("account_service", "account_replication_cluster", "SYNC_RECORD", True),
    ("account_service", "account_failover_replica", "SYNC_RECORD", True),
    ("notification_service", "email_delivery_service", "SEND_EMAIL", False),
    ("support_platform", "search_service", "UPDATE_RECORD", False),
    ("security_service", "archive_service", "RETAIN_RECORD", False),
    ("export_service", "object_store", "CREATE_EXPORT", False),
    ("integration_service", "search_service", "SYNC_RECORD", True),
    ("backup_service", "search_service", "RESTORE_BACKUP", True),
    ("privacy_intake", "privacy_case_management", "CLASSIFY_REQUEST", False),
]
INFERRED = [
    ("account_service", "identity_service", "tombstone derived from the account (rule_15)"),
    ("account_service", "backup_service", "backup entries carry customer references"),
    ("account_service", "integration_service", "connectors select a subject and stream customer events"),
    ("integration_service", "analytics_platform", "connector destination is customer_analytics_warehouse"),
    ("support_platform", "object_storage", "attachment catalog places ticket attachments here"),
]
G = nx.DiGraph()
sys_stats = {r["system"]: r for r in sys_rank}
res_by_sys = act.groupby("target_system").resource_id.nunique().to_dict()
for sid, (label, tier, cat, rids, action) in SYSTEMS.items():
    s = sys_stats.get(sid)
    if not s:  # systems that only originate events: use the events they send
        g = act[act.source_system == sid]
        s = {"n": len(g), "bad": int(g.bad.sum()), "rate": round(float(g.bad.mean()), 4) if len(g) else None, "next_bad": None}
        res_by_sys[sid] = int(g.resource_id.nunique())
    G.add_node(sid, label=label, tier=tier, category=cat, rules=rids, action=action,
               events=int(s.get("n", 0)), failures=int(s.get("bad", 0)), fail_rate=s.get("rate"),
               next_bad=s.get("next_bad"), resources=int(res_by_sys.get(sid, 0)),
               snap_resources=int(snap_stats.get(sid, {}).get("resources", 0)),
               snap_identifiers=int(snap_stats.get(sid, {}).get("with_identifiers", 0)))
for a, b, et, active in OBSERVED:
    g = act[(act.source_system == a) & (act.target_system == b) & (act.event_type == et)]
    G.add_edge(a, b, kind="observed", op=et, events=int(len(g)), fail_rate=round(float(g.bad.mean()), 4) if len(g) else 0.0,
               active=bool(active), restore=(et == "RESTORE_BACKUP"), first=g.event_time.min(), last=g.event_time.max())
for a, b, why in INFERRED:
    G.add_edge(a, b, kind="inferred", op="", events=0, fail_rate=0.0, active=("integration_service" in (a, b)),
               restore=False, why=why)
assert nx.is_directed_acyclic_graph(G), "layered layout expects a DAG"
btw = nx.betweenness_centrality(G)
for n in G.nodes:
    G.nodes[n]["blast_radius"] = len(nx.descendants(G, n))
    G.nodes[n]["betweenness"] = round(btw[n], 4)
graph_json = nx.node_link_data(G, edges="edges")

# --------------------------------------------------------------------------- assemble
months_label = {m: pd.Timestamp(m + "-01").strftime("%b") for m in MONTHS}
total_bad = int(act.bad.sum())
out = {
    "meta": {
        "as_of": AS_OF.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "activity_from": act.t.min().strftime("%Y-%m-%d"), "activity_to": act.t.max().strftime("%Y-%m-%d"),
        "events": int(len(act)), "requests": requests_n, "evidence_files": len(manifest), "sql_snapshots": len(snapshot_meta),
        "rules": len(rules), "months": MONTHS, "month_labels": months_label,
        "oct_partial_events": int((act.month == "2026-10").sum()),
        "networkx": nx.__version__,
    },
    "kpis": {
        "events": int(len(act)), "non_success": total_bad, "non_success_rate": round(total_bad / len(act), 4),
        "destructive_n": int(len(ctrl)), "destructive_bad": int(ctrl.bad.sum()), "destructive_rate": round(float(ctrl.bad.mean()), 4),
        "reborn": len(reborn), "flows_checked": int(len(act[act.event_type == "CHECK_DATA_FLOW"])), "flows_open_act": flows_open_act,
        "restore_checked": int(len(act[act.event_type == "CHECK_RESTORE_ACCESS"])), "restore_open_act": backups_open_act,
        "ghost_rows": ghost_total, "replica_tables": len(rs),
    },
    "rate_series": rate_ser, "rate_fc": rate_fc, "count_fc": count_fc, "ctrl_series": ctrl_ser, "ctrl_fc": ctrl_fc,
    "patterns": patterns_out, "heatmap": {"systems": HEAT_SYS, "rows": heat},
    "systems_rank": sys_rank, "predictor": {"table": pred_tbl, "class_rate": cls_rate},
    "drift": drift_rows,
    "register": register, "aging": {"bins": BINS, "series": aging},
    "retention": {"audit_by_year": sorted(ret_years.items()), "legal_by_year": sorted(legal_years.items()),
                  "legal_register": legal_register, "legal_file": legal_file, "security_extract": sec_file,
                  "security_extract_note": "audit_record_003, retain until 25 Aug 2027"},
    "identifier_fields": ident_fields,
    "unresolved_by_system": sorted(unresolved.items(), key=lambda kv: -kv[1]),
    "graph": graph_json,
    "rules": [{"id": r["rule_id"], "category": r["data_category"], "condition": r["condition"], "action": r["required_action"]} for r in rules],
}
OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False, default=str).replace("<", "\u003c"), encoding="utf-8")

# --------------------------------------------------------------------------- console summary
print(f"wrote {OUT} ({OUT.stat().st_size/1024:.1f} KB); as_of={out['meta']['as_of']}")
print("KPIs:", json.dumps(out["kpis"]))
for p in patterns_out:
    f1 = p["forecast"][0] if p["forecast"] else {}
    print(f"{p['id']} {p['name'][:46]:46s} n={p['n']:5d} count={p['count']:4d} rate={p['rate']} trend={p['trend']:7s} p={p['p']} next={f1.get('y')} [{f1.get('lo')},{f1.get('hi')}] conf={p['confidence']}")
print("overall rate fc:", rate_fc["slope"], rate_fc["p"], rate_fc["fc"][0])
print("register:", {r["id"]: r["n"] for r in register})
print("retention:", out["retention"]["audit_by_year"], out["retention"]["legal_by_year"], len(legal_register))
print("aging:", [(a["label"], a["total"], a["bins"]) for a in aging])
print("ident fields:", ident_fields)
print("unresolved:", dict(unresolved))
print("graph:", G.number_of_nodes(), "nodes", G.number_of_edges(), "edges;", sum(1 for _, _, d in G.edges(data=True) if d["active"]), "active")
print("replica series sample:", rs[:3])
