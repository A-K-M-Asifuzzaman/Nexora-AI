"""Virus scanning (SECURITY.md §8/§12).

`NoOpScanner` is the default — scanning is off unless a deployment
explicitly configures a ClamAV daemon (`ANTIVIRUS_ENABLED=true`), the same
posture as every other optional integration in this project (matches how a
missing LLM key degrades AI features rather than failing startup).

`ClamdScanner` speaks clamd's INSTREAM protocol directly over a raw socket —
no clamd Python client is a dependency of this project, and the protocol
itself is small enough that a dependency would buy little: send the payload
in `<size><chunk>` frames prefixed by a 4-byte big-endian length, terminated
by a zero-length frame, read back one line (`OK`, `FOUND`, or `ERROR`).
"""

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.core.config import Settings

_CHUNK_SIZE = 1024 * 1024  # clamd's own default StreamMaxLength is far larger.
_FOUND = re.compile(r"^stream: (?P<signature>.+) FOUND$")


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    signature: str | None = None


class AntivirusScanner(Protocol):
    async def scan(self, data: bytes) -> ScanResult: ...


class NoOpScanner:
    """The interface's default. Every call reports clean without looking —
    the honest name for "scanning is not configured", not a claim that
    anything was actually checked."""

    async def scan(self, data: bytes) -> ScanResult:
        return ScanResult(clean=True)


class ClamdScanner:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    async def scan(self, data: bytes) -> ScanResult:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), timeout=self._timeout
        )
        try:
            writer.write(b"zINSTREAM\0")
            for offset in range(0, len(data), _CHUNK_SIZE):
                chunk = data[offset : offset + _CHUNK_SIZE]
                writer.write(len(chunk).to_bytes(4, "big") + chunk)
            writer.write((0).to_bytes(4, "big"))
            await asyncio.wait_for(writer.drain(), timeout=self._timeout)

            raw = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
            response = raw.decode("utf-8", errors="replace").strip("\x00").strip()
        finally:
            writer.close()
            await writer.wait_closed()

        if response == "stream: OK":
            return ScanResult(clean=True)
        found = _FOUND.match(response)
        if found:
            return ScanResult(clean=False, signature=found.group("signature"))
        # A malformed or unexpected reply is a scanner problem, not a
        # clean bill of health — the caller must not treat this as "clean".
        raise RuntimeError(f"Unexpected clamd response: {response!r}")


def build_scanner(settings: "Settings") -> AntivirusScanner:
    if not settings.antivirus_enabled:
        return NoOpScanner()
    return ClamdScanner(settings.clamd_host, settings.clamd_port, settings.clamd_timeout_seconds)
