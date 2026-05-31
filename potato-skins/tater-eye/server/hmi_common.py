#!/usr/bin/env python3
"""
hmi_common.py - shared vocabulary for HMI modules.

An HMI's build() returns a dict the front-end renders generically:
    {
      "id":      "<hmi id>",
      "title":   "<display title>",
      "subtitle":"<context line>",
      "channels":[ channel(), ... ],   # the gauge rows
      "notes":   [ note(), ... ],      # the diagnostic stream
      "header":  { label: value, ... } # small KPI strip
    }
Keeping the contract uniform means a new HMI is pure Python - no UI change.
"""

GB = 1024 ** 3
MB = 1024 ** 2

SEV_ORDER = {"alert": 0, "warn": 1, "info": 2, "ok": 3}
STATUS_WORD = {"ok": "NOMINAL", "warn": "WARNING", "alert": "CRITICAL", "info": "ACTIVE"}


def gb(b):
    return b / GB


def fmt_gb(b, p=1):
    return f"{b / GB:.{p}f}"


def fmt_mb(b, p=0):
    return f"{b / MB:.{p}f}"


def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def sev_by_ratio(r, warn_at, alert_at):
    if r >= alert_at:
        return "alert"
    if r >= warn_at:
        return "warn"
    return "ok"


def worst(*sevs):
    """Highest-severity wins (alert > warn > info > ok)."""
    return min(sevs, key=lambda s: SEV_ORDER.get(s, 9))


def note(sev, text, tag=""):
    return {"sev": sev, "text": text, "tag": tag}


def sort_notes(notes):
    notes.sort(key=lambda n: SEV_ORDER.get(n["sev"], 9))
    return notes


def channel(key, label, sub, value, unit, ratio, readout, sev, status=None):
    """One gauge row. ratio is 0..1 for the bar; value/readout are display
    strings already formatted in Python so the front-end stays dumb."""
    return {
        "key": key,
        "label": label,
        "sub": sub,
        "value": value,
        "unit": unit,
        "fill": round(clamp01(ratio) * 100, 1),
        "readout": readout,
        "sev": sev,
        "status": status or STATUS_WORD.get(sev, ""),
    }
