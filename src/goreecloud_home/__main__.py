from __future__ import annotations

import argparse

from .api import HomeStatusServer
from .automation_engine import HomeAutomationEngine
from .automation_runtime import HomeAutomationRuntime
from .core import HomeCore
from .journal import EventJournal


def _parse_listen(value: str) -> tuple[str, int]:
    host, separator, raw_port = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError("listen address must use HOST:PORT")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return host, port


def main() -> None:
    parser = argparse.ArgumentParser(description="GoreeCloud Home Core Development server")
    parser.add_argument("--database", default="./home.db")
    parser.add_argument("--listen", type=_parse_listen, default=("127.0.0.1", 8765))
    args = parser.parse_args()

    journal = EventJournal(args.database)
    core = HomeCore(journal)
    automation_engine = HomeAutomationEngine(core)
    automation_runtime = HomeAutomationRuntime(automation_engine)
    automation_runtime.start()
    server = HomeStatusServer(
        args.listen,
        core,
        automation_engine=automation_engine,
        automation_runtime=automation_runtime,
    )
    host, port = server.server_address[:2]
    print(f"GoreeCloud Home Development status server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        automation_runtime.stop()
        journal.close()


if __name__ == "__main__":
    main()
