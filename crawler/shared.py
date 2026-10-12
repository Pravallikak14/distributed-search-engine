import hashlib
import json


class SharedRobotsCache:
    def __init__(self, redis, prefix="fr:"):
        self.redis = redis
        self.prefix = prefix

    async def get(self, key):
        value = await self.redis.get(self.prefix + "robots:" + key)
        if value is None:
            return None
        return json.loads(value)

    async def set(self, key, value, ttl=86400):
        await self.redis.set(
            self.prefix + "robots:" + key,
            json.dumps(value),
            ex=ttl,
        )


class SharedContentDedupe:
    def __init__(self, redis, key="fr:content"):
        self.redis = redis
        self.key = key

    async def check(self, digest):
        if isinstance(digest, bytes):
            digest = digest.hex()
        elif not isinstance(digest, str):
            digest = str(digest)

        # True means this content was already seen.
        added = await self.redis.sadd(self.key, digest)
        return added == 0

    async def digest(self, content):
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()
