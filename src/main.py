"""
autopi entry-point dispatcher.

Routes CLI flags to the appropriate package under ``src/``. Hyphenated
package directories (``ssm-collector``, ``autopi-app``, ``obd-collector``)
are added to ``sys.path`` before import because they are not valid Python
package names.

Modes
-----
(default)
    SSM terminal logger (``ssm-collector/ssm_main.py``).
``--collector``
    SSM WebSocket collector service (``ssm-collector/ssm_collector.py``).
``--web``
    Dashboard UI only (``autopi-app/web_main.py``); no CAN.
``--obd``
    Generic OBD-II Mode 01 terminal poller (``obd-collector/obd_main.py``).

Typical invocation
------------------
::

    uv run src/main.py
    uv run src/main.py --collector
    uv run src/main.py --web
    uv run src/main.py --obd
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent


def _add_hyphenated_dir(name: str) -> None:
    """
    Prepend ``src/<name>`` to ``sys.path`` so its modules can be imported.

    Args:
        name: Directory name under ``src/`` (e.g. ``\"ssm-collector\"``).
            Must already exist; no validation is performed.
    """
    path = str(_SRC / name)
    if path not in sys.path:
        sys.path.insert(0, path)


def main() -> None:
    """
    Dispatch to the mode selected by ``sys.argv`` flags.

    Flag precedence: ``--obd``, then ``--collector``, then ``--web``,
    otherwise the default SSM terminal logger. Exactly one mode runs;
    overlapping flags are not combined.
    """
    if "--obd" in sys.argv:
        _add_hyphenated_dir("obd-collector")
        from obd_main import main as obd_main

        obd_main()
    elif "--collector" in sys.argv:
        _add_hyphenated_dir("ssm-collector")
        from ssm_collector import main as collector_main

        collector_main()
    elif "--web" in sys.argv:
        _add_hyphenated_dir("autopi-app")
        from web_main import main as web_main

        web_main()
    else:
        _add_hyphenated_dir("ssm-collector")
        from ssm_main import main as ssm_main

        ssm_main()


if __name__ == "__main__":
    main()
