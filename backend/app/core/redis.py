from typing import TYPE_CHECKING

from redis.asyncio import Redis

from app.core.config import Settings

if TYPE_CHECKING:
    # redis-py ships inline type hints where `Redis` is generic, so type checkers
    # get the precise `Redis[str]`.
    RedisClient = Redis[str]
else:
    # At runtime `redis.asyncio.Redis` is NOT subscriptable (redis 6.x):
    #   TypeError: <class 'redis.asyncio.client.Redis'> is not a generic class
    # Annotating a FastAPI dependency as `Redis[str]` therefore raises while the
    # router module is imported, and the application never starts — even though
    # mypy is perfectly happy. Use this alias in annotations, never `Redis[str]`.
    RedisClient = Redis


def create_redis_client(settings: Settings) -> "RedisClient":
    return Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True)
