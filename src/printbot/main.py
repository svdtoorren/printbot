import asyncio
import logging
import signal
import sys

from .config import Settings
from .websocket_client import GatewayClient


def main():
    settings = Settings()
    settings.validate()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("printbot")

    logger.info("PrintBot Gateway starting")
    logger.info("Gateway ID: %s", settings.gateway_id)
    logger.info("Server: %s", settings.ws_url)
    logger.info("Printer: %s", settings.printer_name)

    client = GatewayClient(settings)

    loop = asyncio.new_event_loop()

    def _shutdown(sig):
        logger.info("Received %s, shutting down...", sig.name)
        loop.create_task(client.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown, sig)

    try:
        loop.run_until_complete(client.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
        logger.info("PrintBot Gateway stopped")


if __name__ == "__main__":
    main()
