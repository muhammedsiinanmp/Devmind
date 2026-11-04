"""
Guard for user-supplied URLs that the server will call (BYOK base_url).

Without this a user could point base_url at internal services or cloud
metadata endpoints and have the backend send requests there (SSRF).
"""

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    """Raised when a URL is not a public https URL."""


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def validate_public_https_url(url: str) -> None:
    """
    Raise UnsafeURLError unless `url` uses https and every address its host
    resolves to is public.

    Note: this checks DNS at validation time. It does not stop a host whose
    DNS changes between this check and the request (DNS rebinding).
    """
    try:
        parts = urlsplit(url)
        port = parts.port or 443
    except ValueError as exc:
        raise UnsafeURLError("base_url is not a valid URL") from exc

    if parts.scheme != "https":
        raise UnsafeURLError("base_url must use https")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("base_url must include a host")

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeURLError("base_url host could not be resolved") from exc

    for info in infos:
        address = info[4][0].split("%", 1)[0]  # drop IPv6 zone id
        if not _is_public_ip(ipaddress.ip_address(address)):
            raise UnsafeURLError("base_url must point to a public address")
