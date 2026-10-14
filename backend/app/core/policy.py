"""Exact-origin authorization plus SSRF and conservative read-only URL policy."""
import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from app.core.config import Settings

# Match action words at path/query boundaries, not ordinary substrings ("deletedocs").
ACTION = re.compile(
    r"(?:^|[/_.\-\s])(?:delete|remove|destroy|drop|truncate|logout|signout|unsubscribe|"
    r"reset|revoke|shutdown|purchase|pay|placeorder|confirmorder|addtocart|"
    r"clearcart|checkout|register|signup|upload|changepassword)(?:$|[/_.\-\s])",
    re.I,
)
SENSITIVE_KEYS = re.compile(
    r"^(?:action|cmd|command|do|delete|remove|logout|reset|password|passwd|token|"
    r"access_token|secret|session|authorization|api_key)$", re.I
)
FORBIDDEN_HOSTS = {"metadata.google.internal", "instance-data", "metadata", "host.docker.internal"}
FORBIDDEN_IPS = {"169.254.169.254", "100.100.100.200", "168.63.129.16"}


class PolicyError(ValueError):
    pass


def normalized_url(value: str) -> str:
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise PolicyError("URLs cannot contain whitespace, control characters, or backslashes.")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"}:
            raise PolicyError("Only http:// and https:// URLs are supported.")
        if parts.username is not None or parts.password is not None:
            raise PolicyError("Credentials in URLs are forbidden.")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise PolicyError("A valid hostname is required.")
        try:
            ip = ipaddress.ip_address(host)
            host = ip.compressed
        except ValueError:
            host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.\-]*[a-z0-9])?", host):
                raise PolicyError("Invalid hostname.")
            if any(len(label) > 63 or not label or label.startswith("-") or label.endswith("-")
                   for label in host.split(".")):
                raise PolicyError("Invalid DNS hostname.")
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        if not 1 <= port <= 65535:
            raise PolicyError("Invalid port.")
        if port in {22, 25, 53, 110, 139, 143, 389, 445, 465, 587, 636, 2375, 2376, 6379, 11211}:
            raise PolicyError("This service port is not permitted for website testing.")
        netloc = f"[{host}]" if ":" in host else host
        default = 443 if parts.scheme.lower() == "https" else 80
        if port != default:
            netloc += f":{port}"
        if host in FORBIDDEN_HOSTS:
            raise PolicyError("Infrastructure metadata targets are forbidden.")
        result = urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, parts.fragment))
        if not safe_read_url(result):
            raise PolicyError("This URL appears to perform a state-changing or credential-bearing action.")
        return result
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, PolicyError):
            raise
        raise PolicyError("Malformed URL.") from exc


def origin(value: str) -> str:
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    port = parts.port or (443 if scheme == "https" else 80)
    host = (parts.hostname or "").rstrip(".").lower()
    host = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host}:{port}"


STATIC_ASSET_EXTS = re.compile(
    r"\.(?:js|mjs|css|png|jpg|jpeg|gif|svg|webp|ico|woff2?|ttf|eot|otf|map|webmanifest)$",
    re.I,
)


def safe_read_url(value: str) -> bool:
    parts = urlsplit(value)
    path = unquote(unquote(parts.path))
    fragment = unquote(unquote(parts.fragment))
    # Static frontend assets (scripts, stylesheets, fonts, images) are safe read-only dependencies
    if STATIC_ASSET_EXTS.search(path):
        return True
    # Navigating to a signup/checkout screen is read-only; sending an action to an endpoint isn't.
    if ACTION.search(path):
        return False
    if fragment and re.search(r"(?:^|/)logout(?:$|/|\?)", fragment, re.I):
        return False
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        if SENSITIVE_KEYS.fullmatch(unquote(key)) or ACTION.search(unquote(val)):
            return False
    return True


NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")


def forbidden_ip(address: str, private_authorized: bool) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip in NAT64_WELL_KNOWN:
            # RFC 6052 Well-Known Prefix (64:ff9b::/96) for IPv4/IPv6 translation (NAT64/DNS64).
            # Python's ipaddress library marks this prefix as reserved. Extract the embedded
            # IPv4 address to correctly validate public vs private safety.
            ip = ipaddress.IPv4Address(ip.packed[-4:])
    if str(ip) in FORBIDDEN_IPS or ip.is_link_local or ip.is_multicast or ip.is_unspecified or (ip.is_reserved and not ip.is_loopback):
        return True
    return not private_authorized and not ip.is_global


@dataclass(frozen=True)
class Target:
    url: str
    origin: str
    hostname: str
    port: int
    addresses: tuple[str, ...]
    authorized: bool


class TargetPolicy:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.allowlist = {origin(normalized_url(x)) for x in settings.approved_origins}

    def is_authorized(self, url: str) -> bool:
        return origin(normalized_url(url)) in self.allowlist

    def validate_literal_host(self, url: str) -> None:
        """Reject obviously forbidden IP literals without making a DNS request."""
        normalized = normalized_url(url)
        host = urlsplit(normalized).hostname or ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return
        authorized = origin(normalized) in self.allowlist
        if forbidden_ip(str(address), authorized):
            raise PolicyError("Private, reserved, or metadata network addresses are blocked unless a safe local origin is explicitly approved.")

    def require_authorized(self, url: str, activity: str) -> None:
        if not self.is_authorized(url):
            raise PolicyError(f"{activity} refused: this exact URL origin is not on the organizer-approved allowlist.")

    async def resolve(self, raw_url: str) -> Target:
        url = normalized_url(raw_url)
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        authorized = origin(url) in self.allowlist
        try:
            rows = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=5
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise PolicyError("The target hostname could not be resolved.") from exc
        addresses = tuple(dict.fromkeys(sorted((row[4][0] for row in rows), key=lambda a: (":" in a, a))))
        if not addresses or any(forbidden_ip(a, authorized) for a in addresses):
            raise PolicyError("Private, reserved, or metadata network addresses are blocked unless a safe local origin is explicitly approved.")
        return Target(url, origin(url), host, port, addresses, authorized)

    def public_description(self) -> dict:
        return {
            "origins": sorted(self.allowlist),
            "max_users": self.settings.max_users,
            "load_seconds": self.settings.load_seconds,
            "max_pages": self.settings.max_pages,
            "require_allowlist_all_scans": self.settings.require_allowlist_all_scans,
            "warning": ("REFUSED: all scans require an organizer-approved exact origin." if self.settings.require_allowlist_all_scans else "Security and load tests refuse non-allowlisted origins; passive checks may run on public sites."),
        }
