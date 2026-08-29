"""Compatibility entrypoint forwarding to the current Qt Quick frontend."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    if "--video-cli" in raw_args:
        from ..cli import main as video_main

        marker = raw_args.index("--video-cli")
        return video_main(raw_args[marker + 1 :])

    from .frontend.app import main as qml_main

    return qml_main(raw_args)


if __name__ == "__main__":
    raise SystemExit(main())
