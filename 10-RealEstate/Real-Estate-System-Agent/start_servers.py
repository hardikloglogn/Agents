"""
start_servers.py
════════════════
Start or stop all 8 PropTech Realty AI servers.
(7 specialist MCP servers + 1 supervisor — Direct Answering Agent is embedded in supervisor/graph.py)

Usage:
    python start_servers.py          # start all servers + block
    python start_servers.py --stop   # stop all running servers
"""

import sys
import os
import time
import signal
import argparse
import subprocess
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [PropServers]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SERVERS = [
    {"name": "Property Listing Agent",      "module": "mcp_servers.listing_server",   "port": 8001},
    {"name": "Client & Lead Agent",          "module": "mcp_servers.client_server",    "port": 8002},
    {"name": "Property Search Agent",        "module": "mcp_servers.search_server",    "port": 8003},
    {"name": "Viewing & Appointment Agent",  "module": "mcp_servers.viewing_server",   "port": 8004},
    {"name": "Offer & Deal Agent",           "module": "mcp_servers.offer_server",     "port": 8005},
    {"name": "Document & Legal Agent",       "module": "mcp_servers.document_server",  "port": 8006},
    {"name": "Market Analytics Agent",       "module": "mcp_servers.analytics_server", "port": 8007},
    # Direct Answering Agent is EMBEDDED in supervisor — no server entry here
    {"name": "Supervisor Agent",             "module": "supervisor.supervisor_server", "port": 9001},
]

_processes: list[subprocess.Popen] = []
_log_handles: list = []
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def _launch(server: dict) -> subprocess.Popen | None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        safe_name = server["name"].lower().replace("&", "and").replace(" ", "_")
        log_path = os.path.join(LOG_DIR, f"{safe_name}.log")
        log_file = open(log_path, "w", encoding="utf-8", buffering=1)
        _log_handles.append(log_file)
        p = subprocess.Popen(
            [sys.executable, "-m", server["module"]],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stdout=log_file,
            stderr=log_file,
        )
        log.info("✅  %-35s  port %-5d  PID %d  log: %s", server["name"], server["port"], p.pid, log_path)
        return p
    except Exception as exc:
        log.error("❌  Failed to start %s: %s", server["name"], exc)
        return None


def _stop_all():
    log.info("Stopping %d server(s)…", len(_processes))
    for p in _processes:
        try: p.terminate()
        except Exception: pass
    time.sleep(1.5)
    for p in _processes:
        try:
            if p.poll() is None: p.kill()
        except Exception: pass
    for fh in _log_handles:
        try:
            fh.close()
        except Exception:
            pass
    log.info("All servers stopped.")


def _sig(sig, frame):
    log.info("\n🛑  Shutting down…")
    _stop_all()
    sys.exit(0)


def start():
    from database.db import init_db
    # Ensure no stale PropTech processes are holding target ports.
    stop()
    log.info("Initialising database…")
    init_db()
    log.info("Starting %d servers…\n", len(SERVERS))
    log.info("ℹ️   Direct Answering Agent is embedded in the Supervisor — no separate server.")

    # Specialist agents first (8001-8007)
    for srv in SERVERS[:-1]:
        p = _launch(srv)
        if p: _processes.append(p)
        time.sleep(0.4)

    log.info("Waiting 3s for specialist agents to be ready…")
    time.sleep(3)

    # Supervisor last (9001)
    p = _launch(SERVERS[-1])
    if p: _processes.append(p)

    log.info(
        "\n══════════════════════════════════════════════════\n"
        "  🏠  PropTech Realty AI — All servers running!\n"
        "  Streamlit UI:  streamlit run app.py\n"
        "  UI URL:        http://localhost:8501\n"
        "  Supervisor:    http://127.0.0.1:9001/mcp\n"
        f"  Logs folder:   {LOG_DIR}\n"
        "  General Agent: EMBEDDED in supervisor (no port)\n"
        "  Press Ctrl-C to stop all servers.\n"
        "══════════════════════════════════════════════════"
    )

    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)

    while True:
        time.sleep(5)
        for srv, proc in zip(SERVERS, _processes):
            if proc.poll() is not None:
                log.warning("⚠️  Server '%s' (port %d) exited unexpectedly.", srv["name"], srv["port"])


def stop():
    try:
        import psutil
    except ImportError:
        log.error("psutil not installed. Run: pip install psutil")
        return
    ports = {s["port"] for s in SERVERS}
    killed = 0
    for proc in psutil.process_iter(["pid"]):
        try:
            for conn in proc.net_connections(kind="inet"):
                if conn.laddr.port in ports:
                    proc.terminate()
                    log.info("Stopped PID %d on port %d", proc.pid, conn.laddr.port)
                    killed += 1
                    break
        except Exception:
            pass
    if not killed:
        log.info("No PropTech servers found running.")
    else:
        log.info("Stopped %d server(s).", killed)


def main():
    parser = argparse.ArgumentParser(description="PropTech Realty AI — Server Manager")
    parser.add_argument("--stop", action="store_true", help="Stop all running servers")
    args = parser.parse_args()
    stop() if args.stop else start()


if __name__ == "__main__":
    main()
