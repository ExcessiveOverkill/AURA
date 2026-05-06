"""
RegProbe — Python client for the generated reg_host binary protocol.

Wire format (little-endian):
  Request:  [CMD:1] [ADDR:2LE] [COUNT:2LE] [DATA: COUNT * word_bytes]
  Response: [STATUS:1] [DATA: COUNT * word_bytes]   (data only on reads)
"""

import enum
import struct
import subprocess
from typing import List, Tuple


class RegStatus(enum.IntEnum):
    OK                    = 0
    OK_ATOMIC_BUFFERED    = 1
    OK_ATOMIC_UPDATED     = 2
    BAD_ADDRESS_OUT_OF_RANGE = 3
    BAD_ADDRESS           = 4
    BAD_ACCESS_READ_ONLY  = 5
    BAD_ACCESS_WRITE_ONLY = 6
    BITS_ABOVE_WIDTH      = 7
    REGISTER_OVERFLOW     = 8
    OUT_OF_RANGE          = 9
    BAD_RETURN            = 10


_CMD_READ      = 0x01
_CMD_WRITE     = 0x02
_CMD_RESET     = 0x03
_CMD_VERIFY    = 0x04
_CMD_META_READ = 0x05

_WORD_FMT = {1: "B", 2: "H", 4: "I"}


class RegProbe:
    """
    Wraps a running reg_host subprocess and speaks the binary register protocol.

    Usage::

        with RegProbe("/path/to/test_mod_test", word_bytes=4) as probe:
            probe.reset()
            status, words = probe.read(0x0000)
            status = probe.write(0x0001, [0xAB])
            ok = probe.verify()
    """

    def __init__(self, binary: str, word_bytes: int = 4):
        if word_bytes not in _WORD_FMT:
            raise ValueError(f"word_bytes must be 1, 2, or 4; got {word_bytes}")
        self._word_bytes = word_bytes
        self._fmt = _WORD_FMT[word_bytes]
        self._proc = subprocess.Popen(
            [binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            self._proc.wait(timeout=5)

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def _send(self, data: bytes):
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def _recv(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._proc.stdout.read(n - len(buf))
            if not chunk:
                raise IOError("reg_host process closed unexpectedly")
            buf += chunk
        return buf

    def _pack(self, words: List[int]) -> bytes:
        return struct.pack(f"<{len(words)}{self._fmt}", *words)

    def _unpack(self, data: bytes) -> List[int]:
        n = len(data) // self._word_bytes
        return list(struct.unpack(f"<{n}{self._fmt}", data))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, addr: int, count: int = 1) -> Tuple[RegStatus, List[int]]:
        """Read `count` words from `addr`. Returns (status, [words])."""
        self._send(struct.pack("<BHH", _CMD_READ, addr, count))
        status = RegStatus(self._recv(1)[0])
        ok = status in (RegStatus.OK, RegStatus.OK_ATOMIC_BUFFERED, RegStatus.OK_ATOMIC_UPDATED)
        words = self._unpack(self._recv(count * self._word_bytes)) if ok else []
        return status, words

    def write(self, addr: int, words: List[int]) -> RegStatus:
        """Write `words` starting at `addr`. Returns status."""
        pkt = struct.pack("<BHH", _CMD_WRITE, addr, len(words))
        pkt += self._pack(words)
        self._send(pkt)
        return RegStatus(self._recv(1)[0])

    def reset(self) -> None:
        """Zero all register storage and clear pending buffers."""
        self._send(struct.pack("<BHH", _CMD_RESET, 0, 0))
        self._recv(1)

    def verify(self) -> bool:
        """Run the C++ accessor verify function. Returns True on pass."""
        self._send(struct.pack("<BHH", _CMD_VERIFY, 0, 0))
        return self._recv(1)[0] == 0

    def read_meta_chunk(self, offset: int, count: int = 128) -> bytes:
        """Read `count` raw bytes from the meta blob at byte `offset`."""
        self._send(struct.pack("<BHH", _CMD_META_READ, offset, count))
        status = self._recv(1)[0]
        if status != 0:
            raise IOError(f"meta_read failed: offset={offset} count={count} status={status}")
        return self._recv(count)

    def read_full_meta(self) -> bytes:
        """Read the full meta blob from the device."""
        header = self.read_meta_chunk(0, 12)
        total_size = struct.unpack_from("<I", header, 8)[0]
        if total_size <= 12:
            return header
        rest = self.read_meta_chunk(12, total_size - 12)
        return header + rest
