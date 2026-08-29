"""Network-value helpers.

Several tables store the client address in a PostgreSQL `INET` column, which
rejects anything that is not a real IP. The client address is not guaranteed to
be one — a misconfigured reverse proxy, a unix socket, or a test client can all
supply something else. Coercing here keeps a bad address from failing the write
it is merely annotating.
"""

import ipaddress


def coerce_ip(value: str | None) -> str | None:
    """Return `value` if it parses as an IPv4/IPv6 address, else None.

    Used for every `INET` column. Without it a non-IP client address raises
    `DataError` and takes down the surrounding operation — losing a login, or a
    record of a failed one, because its source address did not parse is exactly
    backwards.
    """
    if value is None:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value
