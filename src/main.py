"""
Default entry point — runs the SSM terminal logger.

  (default)       terminal SSM logger
  --collector     SSM data collector (WebSocket feed, no UI)
  --web           dashboard UI only (connects to collector)
  --obd           generic OBD-II poller
"""

import sys


def main() -> None:
    if "--obd" in sys.argv:
        from obd_main import main as obd_main
        obd_main()
    elif "--collector" in sys.argv:
        from ssm_collector import main as collector_main
        collector_main()
    elif "--web" in sys.argv:
        from web_main import main as web_main
        web_main()
    else:
        from ssm_main import main as ssm_main
        ssm_main()


if __name__ == "__main__":
    main()
