"""Evidence must not disclose cookie values, credentials, or environment secrets."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_KEY = re.compile(r"token|secret|password|passwd|api.?key|authorization|session|cookie", re.I)
SECRET = re.compile(r"(?i)([\w-]*(?:token|secret|password|passwd|api[_-]?key)[\w-]*\s*[:=]\s*)[^\s,;\"<>]+")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def redact(text: str, limit: int = 3000) -> str:
    value = JWT.sub("[REDACTED JWT]", text)
    value = SECRET.sub(r"\1[REDACTED]", value)
    value = re.sub(r"(?im)^((?:set-cookie|cookie|authorization):).*?$", r"\1 [REDACTED]", value)
    return value[:limit]


def safe_url(value: str) -> str:
    p = urlsplit(value)
    query = urlencode([(k, "[REDACTED]" if SECRET_KEY.search(k) else v)
                       for k, v in parse_qsl(p.query, keep_blank_values=True)])
    return urlunsplit((p.scheme, p.netloc, p.path, query, p.fragment))
