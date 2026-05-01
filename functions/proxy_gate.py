import random
import database.db as db
from config import OWNER_IDS
from functions.emojis import EMOJI

NO_PROXY_MSG = (
    f"{EMOJI['declined']} <b>Proxy required!</b>\n\n"
    f"You must add at least one proxy to use any gate.\n\n"
    f"Add a proxy first:\n"
    f"<code>/proxy add host:port:user:pass</code>\n"
    f"<i>Formats: host:port | host:port:user:pass | user:pass@host:port</i>"
)


def _format_proxy_url(proxy_str: str) -> str | None:
    proxy_str = proxy_str.strip()
    try:
        if "@" in proxy_str:
            auth, hostport = proxy_str.rsplit("@", 1)
            user, password = auth.split(":", 1)
            host, port = hostport.rsplit(":", 1)
            return f"http://{user}:{password}@{host}:{port}"
        parts = proxy_str.split(":")
        if len(parts) == 4:
            host, port, user, password = parts
            return f"http://{user}:{password}@{host}:{port}"
        if len(parts) == 2:
            return f"http://{parts[0]}:{parts[1]}"
    except Exception:
        pass
    return None


async def get_user_proxy(uid: int) -> tuple[bool, str | None, str]:
    """Returns (ok, proxy_url, error_msg).

    ok=True  — gate may proceed; proxy_url is the formatted URL
               (may be None for admins/owners who have no proxies).
    ok=False — user has no proxy; error_msg is the message to send.
    Admins/owners bypass the requirement but still get their proxy if available.
    """
    proxies = await db.get_proxies(uid)
    if proxies:
        return True, _format_proxy_url(random.choice(proxies)), ""

    if uid in OWNER_IDS or await db.is_admin(uid):
        return True, None, ""

    return False, None, NO_PROXY_MSG


async def get_user_proxy_dict(uid: int) -> tuple[bool, dict | None, str]:
    """Returns (ok, proxy_dict for the requests library, error_msg)."""
    ok, url, err = await get_user_proxy(uid)
    if not ok:
        return False, None, err
    if url is None:
        return True, None, ""
    return True, {"http": url, "https": url}, ""
