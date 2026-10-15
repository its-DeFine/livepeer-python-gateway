"""Tests for raw byte request bodies in call_runner.

``payload`` keeps sending JSON. ``content`` sends the bytes as is with the given
content type, and the two are mutually exclusive.
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web

from livepeer_gateway.errors import LivepeerGatewayError
from livepeer_gateway.live_runner import call_runner

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 40


def _run(app: web.Application, scenario):
    """Serve `app` on an ephemeral port and run `scenario(base_url)`."""

    async def main():
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            return await scenario(f"http://127.0.0.1:{port}")
        finally:
            await runner.cleanup()

    return asyncio.run(main())


def _echo_app(seen: dict) -> web.Application:
    async def handler(request: web.Request) -> web.Response:
        seen["body"] = await request.read()
        seen["content_type"] = request.headers.get("Content-Type", "")
        seen["method"] = request.method
        return web.json_response({"received": len(seen["body"])})

    app = web.Application()
    app.router.add_route("*", "/in", handler)
    return app


def test_bytes_sent_as_is_with_content_type():
    seen: dict = {}

    async def scenario(base):
        return await call_runner(f"{base}/in", content=FAKE_PNG, content_type="image/png")

    result = _run(_echo_app(seen), scenario)
    assert seen["body"] == FAKE_PNG
    assert seen["content_type"] == "image/png"
    assert seen["method"] == "POST"
    assert result.data == {"received": len(FAKE_PNG)}


def test_bytes_default_content_type_is_octet_stream():
    seen: dict = {}

    async def scenario(base):
        return await call_runner(f"{base}/in", content=b"\x00\x01\x02")

    _run(_echo_app(seen), scenario)
    assert seen["body"] == b"\x00\x01\x02"
    assert seen["content_type"] == "application/octet-stream"


def test_empty_bytes_body_is_sent_as_post():
    seen: dict = {}

    async def scenario(base):
        return await call_runner(f"{base}/in", content=b"")

    _run(_echo_app(seen), scenario)
    assert seen["method"] == "POST"
    assert seen["body"] == b""


def test_json_payload_unchanged():
    seen: dict = {}

    async def scenario(base):
        return await call_runner(f"{base}/in", payload={"x": 1})

    _run(_echo_app(seen), scenario)
    assert seen["content_type"] == "application/json"
    assert seen["body"] == b'{"x": 1}'


def test_bytes_with_stream():
    seen: dict = {}

    async def scenario(base):
        async with await call_runner(
            f"{base}/in", content=FAKE_PNG, content_type="image/png", stream=True
        ) as stream:
            return b"".join([chunk async for chunk in stream.aiter_bytes()])

    body = _run(_echo_app(seen), scenario)
    assert seen["body"] == FAKE_PNG
    assert seen["content_type"] == "image/png"
    assert b"received" in body


def test_payload_and_data_are_mutually_exclusive():
    async def scenario(base):
        return await call_runner(f"{base}/in", payload={"x": 1}, content=b"y")

    with pytest.raises(LivepeerGatewayError):
        _run(_echo_app({}), scenario)
