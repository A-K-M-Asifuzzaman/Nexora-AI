"""Rate limits for the authentication surface (API.md §9).

These are the endpoints an unauthenticated attacker can reach, so they carry the
whole weight of brute-force and enumeration resistance. `SlidingWindowRateLimiter`
existed before this module but was wired to nothing — the limits were specified
and unenforced.

**These fail closed** (SECURITY.md §6). If Redis is unavailable the request is
rejected rather than allowed: a Redis outage must not silently open an unlimited
password-guessing window. Read endpoints make the opposite trade; auth does not.
"""

from dataclasses import dataclass

from redis.exceptions import RedisError

from app.core.errors import AppError, RateLimitedError
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.redis import RedisClient

HOUR = 3600
FIFTEEN_MINUTES = 900


@dataclass(frozen=True, slots=True)
class Limit:
    scope: str
    limit: int
    window_seconds: int


# API.md §9. Per-identifier limits are the ones that stop a targeted attack;
# per-IP limits stop broad sweeps. Both apply.
LOGIN_PER_IDENTITY = Limit("login:id", 5, FIFTEEN_MINUTES)
LOGIN_PER_IP = Limit("login:ip", 20, FIFTEEN_MINUTES)
REGISTER_PER_IP = Limit("register:ip", 3, HOUR)
FORGOT_PER_IDENTITY = Limit("forgot:id", 3, HOUR)
FORGOT_PER_IP = Limit("forgot:ip", 10, HOUR)
REFRESH_PER_SESSION = Limit("refresh:sid", 60, HOUR)

# A TOTP code is 6 digits — a 10^6 space a limiter must actually close off,
# not just discourage. Per-token so a burned-out challenge cannot be waited
# out by re-requesting `/login`; per-IP as the broader backstop.
MFA_CHALLENGE_PER_TOKEN = Limit("mfa:challenge:token", 5, FIFTEEN_MINUTES)
MFA_CHALLENGE_PER_IP = Limit("mfa:challenge:ip", 20, FIFTEEN_MINUTES)


class AuthRateLimiter:
    def __init__(self, redis: RedisClient, *, enabled: bool = True) -> None:
        self._limiter = SlidingWindowRateLimiter(redis)
        self._enabled = enabled

    async def enforce(self, limit: Limit, identifier: str) -> None:
        """Apply one limit, failing closed on Redis errors."""
        if not self._enabled:
            return
        try:
            await self._limiter.check(
                f"{limit.scope}:{identifier}", limit.limit, limit.window_seconds
            )
        except RateLimitedError:
            raise
        except RedisError as exc:
            # Deliberately closed: an attacker who can degrade Redis must not
            # thereby remove the brute-force ceiling.
            raise AppError(
                "SERVICE_UNAVAILABLE",
                "Authentication is temporarily unavailable.",
                503,
            ) from exc

    async def enforce_all(self, *pairs: tuple[Limit, str | None]) -> None:
        for limit, identifier in pairs:
            if identifier:
                await self.enforce(limit, identifier)
