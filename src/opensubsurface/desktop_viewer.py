"""Viewer supervisor. Lives independently of either stdio client; exits after the last lease."""

import os
import sys
import threading
from pathlib import Path

from opensubsurface.desktop_lifecycle import monitor


def main():
    home, port = Path(sys.argv[1]), int(sys.argv[2])
    stopping = threading.Event()
    state = {}

    def shutdown():
        if "server" in state:
            state["server"].should_exit = True
        else:
            os._exit(0)  # No app/controller exists yet; all clients died during imports.

    thread = threading.Thread(target=monitor, args=(home, stopping, shutdown), daemon=True)
    thread.start()
    try:
        import uvicorn

        from opensubsurface.api.app import create_app

        os.environ["OPENSUBSURFACE_PORT"] = str(port)
        app = create_app(root=home, with_ui=True, mcp_profile="agent")
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port))
        state["server"] = server
        server.run()
    finally:
        stopping.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
