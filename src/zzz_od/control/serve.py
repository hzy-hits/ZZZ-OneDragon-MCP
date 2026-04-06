from __future__ import annotations

import argparse

from one_dragon.utils.log_utils import log

from zzz_od.context.zzz_context import ZContext
from zzz_od.control.server import create_control_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OneDragon local control server")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ctx = ZContext()
    ctx.init()

    controller = getattr(ctx, "controller", None)
    if controller is not None:
        try:
            controller.init_before_context_run()
        except Exception as exc:
            log.warning("control server initial window bind failed: %s", exc)

    server = create_control_server(ctx, host=args.host, port=args.port)
    log.info(
        "OneDragon control server listening on http://%s:%s",
        args.host,
        args.port,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("OneDragon control server interrupted")
    finally:
        server.server_close()
        ctx.after_app_shutdown()


if __name__ == "__main__":
    main()
