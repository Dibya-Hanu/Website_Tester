import asyncio
import socket

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.models import CreateJob
from app.core.policy import PolicyError, TargetPolicy, forbidden_ip, normalized_url, origin, safe_read_url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com", "javascript:alert(1)",
    "http://user:password@example.com", "http://example.com\\@localhost/",
    "http://example.com\n/", "http://example.com:22/", "http://example.com:6379/",
    "http://metadata.google.internal", "http://example.com/delete/1", "http://example.com/?action=drop",
    "http://example.com/?password=a", "http://example.com/%64elete/1", "http://example.com/%2564elete/1",
    "http://-invalid.com/", "http://example..com/", "http://example.com:90000/",
])
def test_rejects_unsafe_urls(url):
    with pytest.raises(PolicyError):
        normalized_url(url)


def test_normalizes_origin_and_preserves_spa_route():
    assert normalized_url("HTTP://EXAMPLE.COM:80/#/login") == "http://example.com/#/login"
    assert origin("https://example.com/") == "https://example.com:443"
    assert normalized_url("https://bücher.example/").startswith("https://xn--bcher-kva.example")
    assert safe_read_url("http://example.com/#/checkout")  # Screen navigation; no transaction submits.
    assert not safe_read_url("http://example.com/#/logout")


def test_exact_allowlist_not_product_name_or_substring(settings):
    policy = TargetPolicy(settings)
    assert policy.is_authorized("http://lab.test:3000/a")
    for url in ["https://lab.test:3000/", "http://lab.test:3001/", "http://lab.test.evil:3000/", "http://evil-lab.test:3000/", "http://sub.lab.test:3000/", "https://demo.owasp-juice.shop/"]:
        assert not policy.is_authorized(url)
        with pytest.raises(PolicyError, match="refused"):
            policy.require_authorized(url, "Security")


@pytest.mark.parametrize("address", ["169.254.169.254", "100.100.100.200", "168.63.129.16", "0.0.0.0", "224.0.0.1", "::ffff:169.254.169.254"])
def test_metadata_forbidden_even_if_approved(address):
    assert forbidden_ip(address, private_authorized=True)


def test_private_dns_requires_exact_origin():
    assert forbidden_ip("127.0.0.1", False)
    assert forbidden_ip("10.0.0.1", False)
    assert not forbidden_ip("127.0.0.1", True)
    assert not forbidden_ip("::1", True)
    assert not forbidden_ip("93.184.216.34", False)


async def test_dns_private_mixed_answer_refused(monkeypatch, settings):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(PolicyError, match="Private"):
        await TargetPolicy(settings).resolve("http://public.example/")


async def test_safe_private_origin_resolved_and_pinned(monkeypatch, settings):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.2.0.5", 3000))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    target = await TargetPolicy(settings).resolve("http://lab.test:3000/")
    assert target.authorized and target.addresses == ("10.2.0.5",)


@pytest.mark.parametrize("field,value", [("max_users",21),("load_seconds",31),("max_pages",31),("proxy_rate",21),("max_depth",4)])
def test_hard_caps_cannot_be_increased(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field:value})


def test_request_cannot_override_safety_or_upload_source():
    with pytest.raises(ValidationError):
        CreateJob.model_validate({"url":"http://example.com/","max_users":999})
    with pytest.raises(ValidationError):
        CreateJob.model_validate({"url":"http://example.com/","source_code":"private repository"})
