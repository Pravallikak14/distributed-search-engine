import hashlib


def content_hash(text: str) -> bytes:
    return hashlib.blake2b(
        text.encode("utf-8"),
        digest_size=16,
    ).digest()


class ContentDedupe:
    def __init__(self):
        self._seen: set[bytes] = set()

    def is_duplicate(self, digest: bytes) -> bool:
        """Check-and-add: first time False, tarvatha True."""
        if digest in self._seen:
            return True

        self._seen.add(digest)
        return False

    def __len__(self) -> int:
        return len(self._seen)