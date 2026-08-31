"""Virus scanning (SECURITY.md §8/§12).

`ClamdScanner` is tested against a fake TCP server speaking clamd's actual
INSTREAM wire protocol — not a real ClamAV daemon (heavy, slow to start, not
worth the CI cost for a protocol this small), but a real socket round trip,
so what is proven is the protocol implementation, not just a mocked method.
"""

import asyncio

import pytest

from app.modules.documents.antivirus import ClamdScanner, NoOpScanner, build_scanner
from tests.unit.test_security import settings_fixture


async def test_noop_scanner_always_reports_clean() -> None:
    result = await NoOpScanner().scan(b"anything at all")
    assert result.clean is True
    assert result.signature is None


async def test_build_scanner_returns_noop_when_disabled() -> None:
    settings = settings_fixture()
    assert isinstance(build_scanner(settings), NoOpScanner)


async def test_build_scanner_returns_clamd_when_enabled() -> None:
    settings = settings_fixture().model_copy(update={"antivirus_enabled": True})
    assert isinstance(build_scanner(settings), ClamdScanner)


class _FakeClamd:
    """Speaks just enough of clamd's INSTREAM protocol to prove the client
    frames chunks correctly and parses both response shapes."""

    def __init__(self, response: bytes) -> None:
        self.response = response
        self.received = bytearray()
        self.server: asyncio.AbstractServer | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        greeting = await reader.readexactly(len(b"zINSTREAM\0"))
        assert greeting == b"zINSTREAM\0"
        while True:
            size_bytes = await reader.readexactly(4)
            size = int.from_bytes(size_bytes, "big")
            if size == 0:
                break
            self.received += await reader.readexactly(size)
        writer.write(self.response)
        await writer.drain()
        writer.close()

    async def __aenter__(self) -> tuple[str, int]:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        host, port = self.server.sockets[0].getsockname()[:2]
        return host, port

    async def __aexit__(self, *exc: object) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()


async def test_clamd_scanner_reports_clean_on_ok() -> None:
    async with _FakeClamd(b"stream: OK\0") as (host, port):
        scanner = ClamdScanner(host, port, timeout=5)
        result = await scanner.scan(b"harmless content")
    assert result.clean is True


async def test_clamd_scanner_reports_infected_with_signature() -> None:
    async with _FakeClamd(b"stream: Eicar-Test-Signature FOUND\0") as (host, port):
        scanner = ClamdScanner(host, port, timeout=5)
        result = await scanner.scan(b"fake eicar payload")
    assert result.clean is False
    assert result.signature == "Eicar-Test-Signature"


async def test_clamd_scanner_sends_the_full_payload_correctly_framed() -> None:
    payload = b"x" * 5000
    fake = _FakeClamd(b"stream: OK\0")
    async with fake as (host, port):
        await ClamdScanner(host, port, timeout=5).scan(payload)
    assert bytes(fake.received) == payload


async def test_clamd_scanner_raises_on_an_unrecognized_response() -> None:
    async with _FakeClamd(b"garbage nonsense\0") as (host, port):
        scanner = ClamdScanner(host, port, timeout=5)
        with pytest.raises(RuntimeError, match="Unexpected clamd response"):
            await scanner.scan(b"content")
