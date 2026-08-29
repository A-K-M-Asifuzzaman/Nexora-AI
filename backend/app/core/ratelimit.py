import time

from app.core.errors import RateLimitedError
from app.core.redis import RedisClient


class SlidingWindowRateLimiter:
    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.time()
        start = now - window_seconds
        redis_key = f"ratelimit:{key}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(redis_key, 0, start)
            pipe.zadd(redis_key, {f"{now:.6f}": now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds)
            results = await pipe.execute()
        count = int(results[2])
        if count > limit:
            raise RateLimitedError(window_seconds)
