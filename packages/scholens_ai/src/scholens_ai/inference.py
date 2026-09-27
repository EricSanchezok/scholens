"""CLI for model ownership and lightweight, read-only readiness checks."""

import argparse
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scholens_ai.inference_server import (
        InferenceServer as InferenceServer,
        serve as serve,
    )


def __getattr__(name: str) -> Any:
    # Preserve callers importing the server from the original command module.
    if name not in {"InferenceServer", "serve"}:
        raise AttributeError(name)
    from scholens_ai import inference_server

    value = getattr(inference_server, name)
    globals()[name] = value
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--socket", type=Path, default=os.getenv("SCHOLENS_EMBEDDING_SOCKET")
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.socket is None:
        parser.error("--socket is required")
    if args.check:
        from scholens_ai.inference_health import check_health

        check_health(str(args.socket))
    else:
        import asyncio
        import logging
        from scholens_ai.inference_server import serve

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        asyncio.run(serve(args.socket))


if __name__ == "__main__":
    main()
