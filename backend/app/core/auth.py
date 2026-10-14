"""Authenticated testing helper: handles session cookies and automated login bootstrap."""
import asyncio
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, Error as PlaywrightError
from app.core.config import Settings
from app.core.policy import origin, normalized_url

logger = logging.getLogger(__name__)


def parse_cookie_string(cookie_str: str, domain: str) -> list[dict]:
    """Parse a raw 'key=value; key2=value2' cookie string into Playwright cookie dictionaries."""
    cookies = []
    clean_domain = domain.split(":")[0]
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookies.append({
            "name": key.strip(),
            "value": value.strip(),
            "domain": clean_domain,
            "path": "/",
        })
    return cookies


async def get_authenticated_session(target_url: str, settings: Settings, log=None) -> tuple[list[dict], str | None]:
    """Acquire authenticated session cookies either from cookie config or via automated form login.

    Returns:
        (cookies_list, post_login_url)
    """
    has_creds_file = (settings.ROOT / "credentials.json").exists() or (settings.data_dir / "credentials.json").exists()
    if not settings.auth_enabled and not settings.auth_username and not settings.auth_cookies and not has_creds_file:
        return [], None

    def _log(msg: str):
        if log:
            try:
                log(f"[AUTH] {msg}")
            except Exception:
                pass
        logger.info(f"[AUTH] {msg}")

    target_origin = origin(normalized_url(target_url))
    host = urlsplit(target_url).hostname or "localhost"

    # Multi-site credentials dictionary support (credentials.json in workspace or data_dir)
    site_creds = None
    for cand in [settings.ROOT / "credentials.json", settings.data_dir / "credentials.json"]:
        if cand.exists():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for key, val in data.items():
                        if not isinstance(val, dict):
                            continue
                        try:
                            key_org = origin(normalized_url(key))
                        except Exception:
                            key_org = ""
                        if key_org == target_origin or key.strip().lower() == host.lower():
                            site_creds = val
                            break
                if site_creds:
                    break
            except Exception as err:
                logger.warning(f"Error reading {cand}: {err}")

    # Determine auth parameters: site_creds takes precedence, otherwise fallback to .env settings
    auth_cookies_str = site_creds.get("cookies", "") if site_creds else settings.auth_cookies
    auth_username = (site_creds.get("username", "") if site_creds else settings.auth_username).strip()
    auth_password = site_creds.get("password", "") if site_creds else settings.auth_password
    login_url_raw = (site_creds.get("login_url", "") if site_creds else settings.auth_login_url).strip() or target_url
    user_sel_raw = site_creds.get("user_selector", "") if site_creds else settings.auth_user_selector
    pass_sel_raw = site_creds.get("pass_selector", "") if site_creds else settings.auth_pass_selector
    submit_sel_raw = site_creds.get("submit_selector", "") if site_creds else settings.auth_submit_selector

    # 1. Direct cookie string provided
    if auth_cookies_str:
        cookies = parse_cookie_string(auth_cookies_str, host)
        _log(f"Injected {len(cookies)} manual session cookies from configuration.")
        return cookies, None

    # 2. Automated form login
    if not (auth_username and auth_password):
        return [], None

    login_url = login_url_raw or target_url
    if origin(normalized_url(login_url)) != target_origin:
        _log(f"Login URL origin mismatch: {login_url} vs target {target_origin}. Skipping auto-login.")
        return [], None

    # Check cache first
    cache_dir = settings.data_dir / "auth_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{host}.json"

    user_sel = (user_sel_raw or "").strip() or "input[type='email'],input[name*='user' i],input[name*='email' i],input[name*='login' i],input[type='text']"
    pass_sel = (pass_sel_raw or "").strip() or "input[type='password']"
    submit_sel = (submit_sel_raw or "").strip() or "button[type='submit'],input[type='submit'],button:has-text('Sign In'),button:has-text('Log In'),button:has-text('Login')"

    _log(f"Executing automated login at {login_url} as '{auth_username}'...")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                executable_path=settings.chromium_path or None,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000},
                user_agent=settings.user_agent,
                ignore_https_errors=True
            )
            page = await context.new_page()

            # Navigate to login screen
            await page.goto(login_url, wait_until="domcontentloaded", timeout=settings.request_timeout * 1000)
            await page.wait_for_timeout(600)

            # Fill username
            user_input = page.locator(user_sel).first
            if await user_input.count() > 0:
                await user_input.fill(auth_username)
            else:
                _log(f"Warning: Username field selector '{user_sel}' not found on {login_url}")
                await browser.close()
                return [], None

            # Fill password
            pass_input = page.locator(pass_sel).first
            if await pass_input.count() > 0:
                await pass_input.fill(auth_password)
            else:
                _log(f"Warning: Password field selector '{pass_sel}' not found on {login_url}")
                await browser.close()
                return [], None

            # Submit
            submit_btn = page.locator(submit_sel).first
            if await submit_btn.count() > 0:
                await submit_btn.click()
            else:
                # Fallback to pressing Enter in password input
                await pass_input.press("Enter")

            # Wait for post-login redirect
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
            except PlaywrightError:
                pass
            await page.wait_for_timeout(1500)

            post_login_url = page.url
            cookies = await context.cookies()
            await browser.close()

            if cookies:
                _log(f"Login successful! Captured {len(cookies)} cookies. Landed on {post_login_url}")
                try:
                    cache_file.write_text(json.dumps({"cookies": cookies, "post_url": post_login_url}, indent=2))
                except Exception:
                    pass
                return cookies, post_login_url
            else:
                _log("Warning: Login submitted but no session cookies were captured.")
                return [], None

    except Exception as exc:
        _log(f"Auto-login failed with {type(exc).__name__}: {str(exc)[:200]}")
        return [], None
