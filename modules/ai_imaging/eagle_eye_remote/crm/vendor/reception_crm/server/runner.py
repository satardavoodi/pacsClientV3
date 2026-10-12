"""Headless server process: logging, lifecycle, graceful shutdown.

Used by three callers:
  * ``reception-crm-server`` console command (manual / debugging)
  * the Windows service wrapper (``service.py``)
  * the end-to-end test harness

A service has no console, so every diagnostic goes to a rotating log file
rather than stdout.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .. import politeness, runtime, snapshots
from ..adapters.http_api import create_http_api_server
from .config import ServerConfig, apply_to_environment, config_path, load_server_config, write_default_config

#: How many snapshots one startup will compact. A first run against a year of
#: files would otherwise be an hour of disk I/O on a machine whose real job is a
#: reception desk; bounded, it simply finishes over the next few restarts.
SNAPSHOT_COMPACTION_LIMIT = 500

LOG_FILENAME = "reception-server.log"
logger = logging.getLogger("reception_crm.server")


def configure_logging(config: ServerConfig, *, to_console: bool = False) -> Path:
    """Attach a rotating file handler. Returns the log file path."""
    # runtime.log_root() derives from runtime.data_root(), which reads the
    # RECEPTION_CRM_DATA_ROOT environment variable and otherwise falls back to a
    # hard-coded default. Logging is configured BEFORE apply_to_environment()
    # publishes the configured data_root, so on any machine whose data_root
    # differs from that default the logs silently went to the wrong folder --
    # and created it. On the reception server that meant a stray "D:\RAZI crm"
    # appearing next to the real data folder, with the only record of what the
    # service was doing inside it. Publish the path first, then resolve.
    os.environ["RECEPTION_CRM_DATA_ROOT"] = str(config.data_root)
    log_dir = runtime.ensure_dir(runtime.log_root())
    log_file = log_dir / LOG_FILENAME

    root = logging.getLogger()
    root.setLevel(getattr(logging, config.log_level, logging.INFO))

    # Clear inherited handlers so a service restart does not double-log.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if to_console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

    return log_file


def _start_snapshot_compaction(config: Any, logger: logging.Logger) -> None:
    """Compact settled snapshots once, in the background, after we are listening.

    The snapshot tree grows at roughly 19.3 MB/day and nothing prunes it, on
    purpose: a snapshot is the only record of what a moving system looked like
    when an answer was given. So it is compressed, never deleted, and the
    original is removed only after the gzip has been read back and compared.

    Three things about how it is scheduled, all of which matter more than the
    saving:

    * **After the socket is listening**, so a first run over a year of files
      cannot delay the moment the clinic can use the agent.
    * **On a daemon thread**, so a shutdown never waits for it.
    * **Bounded per run.** It picks up where it left off next start rather than
      turning one restart into an hour of disk I/O on a machine whose real job
      is a reception desk.

    Failures are logged and dropped. This is housekeeping; it must never be the
    reason the server does not come up.
    """
    def run() -> None:
        try:
            root = Path(runtime.data_root()) / "data" / "raw"
            result = snapshots.compact(root, limit=SNAPSHOT_COMPACTION_LIMIT)
            if result.compacted or result.failed:
                logger.info("snapshot compaction: %s", json.dumps(result.as_dict()))
        except Exception as exc:  # noqa: BLE001 - housekeeping must not take the server down
            logger.warning(
                "snapshot compaction did not run (%s: %s); snapshots are untouched",
                type(exc).__name__, exc,
            )

    threading.Thread(target=run, name="snapshot-compaction", daemon=True).start()


class ServerProcess:
    """Owns the HTTP server object so it can be stopped from another thread.

    ``serve_forever()`` blocks. The Windows service control handler runs on a
    different thread and needs a handle to call ``shutdown()``; that is the
    whole reason this class exists rather than a bare function.
    """

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._server: Any = None
        self._started = threading.Event()

    def start(self) -> None:
        config = self.config

        problems = config.validate()
        if problems:
            for problem in problems:
                logger.error("configuration error: %s", problem)
            raise SystemExit("Refusing to start with an invalid configuration.")

        for note in config.warnings():
            logger.warning(note)

        apply_to_environment(config)
        runtime.ensure_dir(Path(config.data_root))

        # Step back from the clinical software before doing anything else. This
        # machine also runs the reception system, MongoDB and the PACS server;
        # under CPU contention they should win, always.
        politeness.apply()

        logger.info("runtime: %s", json.dumps(runtime.describe(), ensure_ascii=False))
        logger.info("config: %s", json.dumps(config.public_dict(), ensure_ascii=False))

        self._server = create_http_api_server(
            config.host,
            config.port,
            tls_certfile=config.tls_certfile or None,
            tls_keyfile=config.tls_keyfile or None,
        )

        logger.info(
            "listening on %s://%s:%s  (local: %s://127.0.0.1:%s)",
            config.scheme,
            config.host,
            config.port,
            config.scheme,
            config.port,
        )
        _start_snapshot_compaction(config, logger)
        if config.bind == "all":
            logger.info(
                "external callers reach this through the forwarded port on the router"
            )

        self._started.set()
        try:
            self._server.serve_forever(poll_interval=0.5)
        finally:
            logger.info("serve loop exited")

    def stop(self) -> None:
        if self._server is None:
            return
        logger.info("stop requested")
        # shutdown() must not be called from the serving thread or it deadlocks.
        threading.Thread(target=self._server.shutdown, daemon=True).start()
        self._server.server_close()
        logger.info("stopped")

    def wait_until_started(self, timeout: float = 10.0) -> bool:
        return self._started.wait(timeout)


def run(config: ServerConfig | None = None, *, to_console: bool = True) -> None:
    config = config or load_server_config()
    log_file = configure_logging(config, to_console=to_console)
    logger.info("--- Reception CRM server starting ---")
    logger.info("log file: %s", log_file)

    process = ServerProcess(config)

    def handle_signal(signum: int, _frame: Any) -> None:
        logger.info("signal %s received", signum)
        process.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, OSError):
            # Not available on every platform/thread; the service path uses its
            # own control handler instead.
            pass

    try:
        process.start()
    except KeyboardInterrupt:
        process.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reception-crm-server",
        description="Run the Reception CRM mobile endpoint (headless).",
    )
    parser.add_argument("--bind", choices=["local", "all"], help="Override configured bind mode.")
    parser.add_argument("--port", type=int, help="Override configured port.")
    parser.add_argument("--config", help="Path to server.json.")
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print resolved paths and configuration, then exit without binding.",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Write a starter server.json if none exists, then exit.",
    )
    parser.add_argument(
        "--generate-secret",
        action="store_true",
        help="Print a fresh random session secret, then exit.",
    )
    bootstrap_group = parser.add_mutually_exclusive_group()
    bootstrap_group.add_argument(
        "--bootstrap-center",
        action="store_true",
        help="Discover this installation's centre catalogue and create review artifacts.",
    )
    bootstrap_group.add_argument(
        "--approve-center-concepts",
        nargs="+",
        metavar="CONCEPT_ID",
        help="Promote explicitly reviewed LLM candidate concept ids.",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="With --bootstrap-center, skip the optional LLM candidate proposal.",
    )
    args = parser.parse_args(argv)
    explicit_config = Path(args.config).resolve() if args.config else None
    if explicit_config is not None:
        # roles.json, centre artifacts and server.json are one configuration
        # set. A support/silent-install command that points at a custom
        # server.json must not scatter the other files into default ProgramData.
        os.environ["RECEPTION_CRM_CONFIG_DIR"] = str(explicit_config.parent)

    if args.generate_secret:
        print(secrets.token_hex(32))
        return 0

    if args.init_config:
        written = write_default_config(explicit_config)
        print(f"config: {written}")
        return 0

    config = load_server_config(explicit_config)
    if args.bootstrap_center:
        from ..center_bootstrap import bootstrap_center
        from ..local.mongo import DEFAULT_DB, ENV_DB, reception_db

        apply_to_environment(config)
        payload = bootstrap_center(
            center=config.center,
            database=reception_db(),
            database_name=os.getenv(ENV_DB) or DEFAULT_DB,
            with_llm=not args.discover_only,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.approve_center_concepts:
        from ..center_bootstrap import promote_candidate_concepts

        apply_to_environment(config)
        payload = promote_candidate_concepts(
            args.approve_center_concepts,
            center=config.center,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.bind:
        config.bind = args.bind
    if args.port:
        config.port = args.port

    if args.describe:
        payload = {
            "runtime": runtime.describe(),
            "config_file": str(config_path()),
            "config": config.public_dict(),
            "problems": config.validate(),
            "warnings": config.warnings(),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    run(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
