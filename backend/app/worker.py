"""External scan-worker entrypoint used by the Docker deployment.

Run exactly one worker per deployment while the scanner adapters and ZAP use
shared single-session state. The native development entrypoint remains inline.
"""
import asyncio
import logging
import signal

from app.core.config import get_settings
from app.core.store import Store
from app.pipeline.runner import JobWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def serve() -> None:
    settings = get_settings()
    settings.prepare()
    if settings.worker_mode != "external":
        logging.getLogger(__name__).warning(
            "UWT_WORKER_MODE is not external; running worker process anyway because app.worker was invoked."
        )
    worker = JobWorker(settings, Store(settings.db_path))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform-specific
            pass
    await worker.start()
    logging.getLogger(__name__).info("External scan worker started; polling the durable job queue.")
    try:
        await stop.wait()
    finally:
        await worker.stop()
        logging.getLogger(__name__).info("External scan worker stopped.")


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
