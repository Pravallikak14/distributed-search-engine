import hashlib
import math


class BloomFilter:
    def __init__(self, capacity: int, error_rate: float = 0.01):
        if capacity <= 0 or not 0 < error_rate < 1:
            raise ValueError("capacity > 0 and 0 < error_rate < 1 required")

        self.capacity = capacity
        self.error_rate = error_rate

        self.num_bits = max(
            8,
            math.ceil(
                -capacity * math.log(error_rate) / (math.log(2) ** 2)
            ),
        )

        self.num_hashes = max(
            1,
            round(self.num_bits / capacity * math.log(2)),
        )

        self._bits = bytearray((self.num_bits + 7) // 8)
        self._count = 0

    def _positions(self, item: str):
        d = hashlib.blake2b(
            item.encode("utf-8"),
            digest_size=16,
        ).digest()

        h1 = int.from_bytes(d[:8], "little")
        h2 = int.from_bytes(d[8:], "little") | 1

        for i in range(self.num_hashes):
            yield (h1 + i * h2) % self.num_bits

    def add(self, item: str) -> bool:
        """Returns True if item was definitely new, False if probably seen."""
        new = False

        for p in self._positions(item):
            byte, mask = p >> 3, 1 << (p & 7)

            if not self._bits[byte] & mask:
                new = True
                self._bits[byte] |= mask

        if new:
            self._count += 1

        return new

    def __contains__(self, item: str) -> bool:
        return all(
            self._bits[p >> 3] & (1 << (p & 7))
            for p in self._positions(item)
        )

    def __len__(self) -> int:
        return self._count

    @property
    def size_bytes(self) -> int:
        return len(self._bits)

    def estimated_fp_rate(self) -> float:
        """Current false-positive probability."""
        return (
            1
            - math.exp(
                -self.num_hashes * self._count / self.num_bits
            )
        ) ** self.num_hashes