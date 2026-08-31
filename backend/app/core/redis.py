from typing import cast

from redis.asyncio import Redis

from app.core.config import Settings

# `redis.asyncio.Redis` is not a generic class — at runtime it is not
# subscriptable at all:
#   TypeError: <class 'redis.asyncio.client.Redis'> is not a generic class
# so annotating a FastAPI dependency as `Redis[str]` raises while the router
# module is imported and the application never starts. As of redis-py 6.4 the
# inline hints agree, so type checkers reject the subscript too. Use this alias
# in annotations, never `Redis[str]`.
RedisClient = Redis


def create_redis_client(settings: Settings) -> RedisClient:
    # `from_url` is annotated as returning Any.
    return cast(
        RedisClient,
        Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True),
    )
