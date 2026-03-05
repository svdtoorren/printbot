"""Mock WebSocket server for local gateway testing.

Usage:
    python -m tests.mock_server

Starts a WebSocket server on ws://localhost:8765/ws/gateway that:
- Accepts any Bearer token
- Sends a test print job on connect
- Logs heartbeats and job status updates
"""

import asyncio
import base64
import json
import logging

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("mock_server")

# Minimal test PDF (blank page)
TEST_PDF = b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n2 0 obj<</Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</MediaBox[0 0 595 842]>>endobj\nxref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"


async def handler(websocket):
    path = websocket.request.path if hasattr(websocket, 'request') else ""
    logger.info("Gateway connected (path=%s)", path)

    # Send a test print job after 2 seconds
    async def send_test_job():
        await asyncio.sleep(2)
        job = {
            "type": "print",
            "job_id": "test-job-001",
            "payload": base64.b64encode(TEST_PDF).decode(),
            "payload_type": "pdf",
            "metadata": {
                "title": "Test Print Job",
                "copies": 1,
                "duplex": False,
            },
        }
        await websocket.send(json.dumps(job))
        logger.info("Sent test print job")

    send_task = asyncio.create_task(send_test_job())

    try:
        async for raw in websocket:
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "heartbeat":
                logger.info(
                    "Heartbeat: printer=%s, version=%s, uptime=%ds",
                    msg.get("printer_status"), msg.get("version"), msg.get("uptime", 0),
                )

            elif msg_type == "job_status":
                logger.info(
                    "Job %s → %s%s",
                    msg.get("job_id"), msg.get("status"),
                    f" (error: {msg['error']})" if msg.get("error") else "",
                )

            elif msg_type == "pong":
                logger.debug("Pong received")

            else:
                logger.info("Received: %s", msg)

    except websockets.ConnectionClosed:
        logger.info("Gateway disconnected")
    finally:
        send_task.cancel()


async def main():
    logger.info("Mock Print Gateway Server starting on ws://localhost:8765/ws/gateway")
    async with websockets.serve(handler, "localhost", 8765):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
