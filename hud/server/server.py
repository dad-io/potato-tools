#!/usr/bin/env python3
"""
server.py - the HUD backend.

Two background sampler threads keep a shared snapshot fresh; the HTTP layer
just renders it. This decouples slow probes (per-process VRAM, LM Studio API,
Core Temp, paging counters - each a few hundred ms) from the fast cadence
(CPU/RAM/GPU/net) so /data always answers instantly with the latest values.

  GET /        -> dashboard (web/index.html + static assets)
  GET /data    -> { "t": epoch, "hmis": [ <llm>, <sys> ] }
"""

import http.server
import json
import os
import threading
import time
from urllib.parse import urlparse

import psutil

import probes
import hmi_sys
import hmi_llm

PORT = 8765
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
FAST_INTERVAL = 2.0
SLOW_INTERVAL = 4.0
PAGE_BYTES = 4096


class State:
    """Shared, lock-guarded snapshot plus the previous counters needed to
    turn cumulative values into rates."""

    def __init__(self):
        self.lock = threading.Lock()
        self.snap = {"cpu": {}, "mem": {}, "gpu": {}, "disk": {}, "net": {},
                     "lmstudio": {"server_up": False, "loaded": []},
                     "lm_pids": set(), "lm_vram": 0, "lm_rss": 0, "lm_cpu": 0.0,
                     "uptime_s": 0.0, "host": probes.host_info()}
        self.boot = psutil.boot_time()
        # rate bookkeeping
        self._prev_net = None
        self._prev_disk = None
        self._prev_t = None
        self._proc_cache = {}  # pid -> psutil.Process (persistent for cpu%)

    # ---- fast loop: cpu / mem / gpu / net / disk-io ----
    def fast_tick(self):
        now = time.time()
        cpu = probes.cpu_sample()
        mem = probes.mem_sample()
        gpu = probes.gpu()
        net = probes.net_sample()
        disk_io = {}
        try:
            io = psutil.disk_io_counters(perdisk=False)
            if io:
                disk_io = {"read_bytes": io.read_bytes, "write_bytes": io.write_bytes}
        except Exception:
            pass

        dt = (now - self._prev_t) if self._prev_t else None
        net_rate = {"up_bps": 0.0, "down_bps": 0.0}
        disk_rate = {"read_bps": 0.0, "write_bps": 0.0}
        if dt and dt > 0:
            if self._prev_net:
                net_rate["up_bps"] = max(0, net.get("bytes_sent", 0) - self._prev_net.get("bytes_sent", 0)) / dt
                net_rate["down_bps"] = max(0, net.get("bytes_recv", 0) - self._prev_net.get("bytes_recv", 0)) / dt
            if self._prev_disk and disk_io:
                disk_rate["read_bps"] = max(0, disk_io.get("read_bytes", 0) - self._prev_disk.get("read_bytes", 0)) / dt
                disk_rate["write_bps"] = max(0, disk_io.get("write_bytes", 0) - self._prev_disk.get("write_bytes", 0)) / dt
        self._prev_net = net
        self._prev_disk = disk_io
        self._prev_t = now

        with self.lock:
            self.snap["cpu"].update(cpu)
            self.snap["mem"].update(mem)
            self.snap["gpu"] = gpu or self.snap["gpu"]
            net.update(net_rate)
            self.snap["net"] = net
            self.snap.setdefault("disk", {}).update(disk_rate)
            self.snap["uptime_s"] = now - self.boot

    # ---- slow loop: per-proc VRAM / LM Studio / Core Temp / paging / volumes ----
    def slow_tick(self):
        vram_by_pid = probes.gpu_proc_vram()
        lm_pids = probes.lmstudio_pids()
        lms = probes.lmstudio()
        ct = probes.coretemp()
        paging = probes.paging_rates()
        drives = [p.device.rstrip("\\")[0] for p in psutil.disk_partitions(all=False)
                  if "fixed" in (p.opts or "") or p.fstype]
        vols = probes.disk_sample(sorted(set(drives)))

        lm_vram = sum(vram_by_pid.get(p, 0) for p in lm_pids)
        lm_rss, lm_cpu = self._tree_resources(lm_pids)

        with self.lock:
            self.snap["lm_pids"] = lm_pids
            self.snap["lm_vram"] = lm_vram
            self.snap["lm_rss"] = lm_rss
            self.snap["lm_cpu"] = lm_cpu
            self.snap["lmstudio"] = lms
            if ct:
                self.snap["cpu"]["temp"] = ct
            self.snap["mem"]["pageout_rate"] = paging["pageout_pps"] * PAGE_BYTES
            self.snap["mem"]["pagein_rate"] = paging["pagein_pps"] * PAGE_BYTES
            self.snap["disk"]["vols"] = vols.get("vols", {})

    def _tree_resources(self, pids):
        """RSS + live CPU% for a set of pids, using persistent Process objects
        so cpu_percent() measures over the interval rather than returning 0."""
        rss = 0
        cpu = 0.0
        # drop stale
        for pid in list(self._proc_cache):
            if pid not in pids:
                self._proc_cache.pop(pid, None)
        for pid in pids:
            try:
                p = self._proc_cache.get(pid)
                if p is None:
                    p = psutil.Process(pid)
                    p.cpu_percent(None)  # prime
                    self._proc_cache[pid] = p
                rss += p.memory_info().rss
                cpu += p.cpu_percent(None)
            except Exception:
                self._proc_cache.pop(pid, None)
        return rss, cpu

    def render(self):
        with self.lock:
            snap = dict(self.snap)  # shallow copy is enough; build() only reads
        # llm first: it sets snap['lm_active'], which the sys HMI consumes.
        llm = hmi_llm.build(snap)
        sysv = hmi_sys.build(snap)
        return {"t": time.time(), "hmis": [llm, sysv]}


STATE = State()


def _fast_loop():
    while True:
        try:
            STATE.fast_tick()
        except Exception as e:
            print("[fast] error:", e)
        time.sleep(FAST_INTERVAL)


def _slow_loop():
    while True:
        try:
            STATE.slow_tick()
        except Exception as e:
            print("[slow] error:", e)
        time.sleep(SLOW_INTERVAL)


_STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css",
                 ".js": "application/javascript", ".svg": "image/svg+xml",
                 ".woff2": "font/woff2", ".png": "image/png"}


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, ctype, body):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/data":
            self._send(200, "application/json",
                       json.dumps(STATE.render()).encode())
            return
        if path == "/" or path == "":
            path = "/index.html"
        # static, sandboxed to WEB_DIR
        rel = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        full = os.path.join(WEB_DIR, rel)
        if not os.path.abspath(full).startswith(os.path.abspath(WEB_DIR)) or not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            self._send(200, _STATIC_TYPES.get(ext, "application/octet-stream"), f.read())

    def log_message(self, *a):
        pass


class _Server(http.server.ThreadingHTTPServer):
    # Windows SO_REUSEADDR lets multiple sockets bind the SAME port, so the
    # stdlib default (allow_reuse_address=True) silently spawns duplicate
    # servers. Force it off: a second instance fails to bind and exits.
    allow_reuse_address = False
    daemon_threads = True


def main():
    threading.Thread(target=_fast_loop, daemon=True).start()
    threading.Thread(target=_slow_loop, daemon=True).start()
    # let the first samples land before serving
    time.sleep(FAST_INTERVAL + 0.2)
    try:
        srv = _Server(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print(f"port {PORT} already in use ({e}); exiting to avoid a duplicate")
        return
    print(f"HUD backend on http://127.0.0.1:{PORT}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
