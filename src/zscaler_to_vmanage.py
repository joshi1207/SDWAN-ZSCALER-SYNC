#!/usr/bin/env python3
"""
Zscaler → Cisco vManage Data Prefix List Sync

- Fetches Zscaler IP ranges (ZPA/ZIA JSON)
- Normalizes to CIDR
- Filters IPv4 / IPv6 (configurable)
- Updates Cisco vManage Data Prefix Lists via REST API
- Supports large lists via chunking into multiple DPLs
- Optional Microsoft Teams notifications

Environment variables can be read from:
- process environment
- .env file in current working directory (auto-loaded)

Author: (your name / company)
License: MIT (see LICENSE)
"""

import os
import sys
import json
import time
import math
import argparse
import logging
from ipaddress import ip_network

import requests

# -----------------------------------------------------------------------------
#  .env loader (simple, no external deps)
# -----------------------------------------------------------------------------

def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (if not already set)."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                # do not override if already set
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception as e:
        print(f"[WARN] Failed to load .env ({path}): {e}", file=sys.stderr)


# Load .env before reading configuration
load_dotenv()

# -----------------------------------------------------------------------------
#  Configuration from environment
# -----------------------------------------------------------------------------

VMANAGE_HOST = os.getenv("VMANAGE_HOST", "localhost")
VMANAGE_PORT = int(os.getenv("VMANAGE_PORT", "8443"))
VMANAGE_USER = os.getenv("VMANAGE_USER", "")
VMANAGE_PASS = os.getenv("VMANAGE_PASS", "")

DPL_NAME = os.getenv("DPL_NAME", "ZSCALER_BYPASS")

# Example for ZPA:
#   https://config.zscaler.com/api/zscaler.net/zpa/json
ZSCALER_JSON_URL = os.getenv("ZSCALER_JSON_URL", "")

CACHE_FILE = os.getenv("CACHE_FILE", "cache.json")
BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Safety guard: block if removals exceed this %
MAX_REMOVE_PERCENT = float(os.getenv("MAX_REMOVE_PERCENT", "25"))

# TLS verification for ALL HTTPS calls
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").lower() == "true"

# IP family filter: ipv4, ipv6, or both
ZSCALER_FAMILY = os.getenv("ZSCALER_FAMILY", "ipv4").lower()  # you mainly use ipv4

# Max entries per Data Prefix List. If exceeded, we create chunks:
#   DPL_NAME_01, DPL_NAME_02, ...
ZSCALER_MAX_CHUNK = int(os.getenv("ZSCALER_MAX_CHUNK", "500"))

# Optional: MS Teams webhook URL for notifications
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")


# -----------------------------------------------------------------------------
#  Logging
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("zscaler-sync")


# -----------------------------------------------------------------------------
#  Helpers: Teams Notification
# -----------------------------------------------------------------------------

def notify_teams(title: str, text: str, success: bool = True) -> None:
    """Send a basic message to a Microsoft Teams incoming webhook (optional)."""
    if not TEAMS_WEBHOOK_URL:
        return
    color = "00FF00" if success else "FF0000"
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": color,
        "title": title,
        "text": text,
    }
    try:
        r = requests.post(
            TEAMS_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
            verify=VERIFY_TLS,
        )
        r.raise_for_status()
    except Exception as e:
        logger.warning("Teams notification failed: %s", e)


# -----------------------------------------------------------------------------
#  Zscaler JSON → CIDR Extraction
# -----------------------------------------------------------------------------

def fetch_zscaler_prefixes(url: str, family: str = "ipv4") -> list[str]:
    """
    Fetch Zscaler JSON and return a sorted list of CIDR strings.
    - family: 'ipv4', 'ipv6', or 'both'
    """
    if not url:
        raise RuntimeError("ZSCALER_JSON_URL not set")

    logger.info("Fetching Zscaler JSON from %s", url)
    r = requests.get(url, timeout=60, verify=VERIFY_TLS)
    r.raise_for_status()

    # some Zscaler endpoints return JSON, some plain arrays, some nested structures
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Failed to parse Zscaler JSON: {e}") from e

    cidrs: set[str] = set()

    def add_cidr(value: str, mask: int | None = None) -> None:
        value = value.strip()
        if not value:
            return
        try:
            if "/" in value:
                net = ip_network(value, strict=False)
            elif mask is not None:
                net = ip_network(f"{value}/{int(mask)}", strict=False)
            else:
                # assume host /32 or /128
                net = ip_network(f"{value}/32", strict=False)
        except Exception:
            return

        if family == "ipv4" and net.version != 4:
            return
        if family == "ipv6" and net.version != 6:
            return

        cidrs.add(f"{net.network_address}/{net.prefixlen}")

    def walk(obj):
        if isinstance(obj, dict):
            # common patterns: 'ipPrefix', 'prefix' + maskX
            if "ipPrefix" in obj:
                add_cidr(str(obj["ipPrefix"]))
            elif "prefix" in obj:
                mask = obj.get("masklength") or obj.get("maskLength") or obj.get("mask")
                add_cidr(str(obj["prefix"]), mask)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str) and "/" in obj:
            add_cidr(obj)

    walk(data)

    lst = sorted(cidrs)
    logger.info("Loaded %d Zscaler CIDRs (family=%s)", len(lst), family)
    return lst


# -----------------------------------------------------------------------------
#  Cache for delta calculations
# -----------------------------------------------------------------------------

def read_cache(path: str) -> list[str]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("Failed to read cache %s: %s", path, e)
        return []


def write_cache(path: str, lst: list[str]) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(sorted(lst), f, indent=2)
    except Exception as e:
        logger.warning("Failed to write cache %s: %s", path, e)


# -----------------------------------------------------------------------------
#  vManage API helpers (pure requests)
# -----------------------------------------------------------------------------

def vm_login() -> tuple[requests.Session, str]:
    """
    Log into vManage using the GUI-style flow:
    - GET /
    - POST /j_security_check
    - GET /dataservice/client/token
    Returns (requests.Session, base_url)
    """
    base = f"https://{VMANAGE_HOST}:{VMANAGE_PORT}"
    s = requests.Session()
    s.verify = VERIFY_TLS

    logger.info("Logging into vManage at %s as %s", base, VMANAGE_USER)

    # Seed cookies
    s.get(base + "/", timeout=30)

    # Login
    r = s.post(
        base + "/j_security_check",
        data={"j_username": VMANAGE_USER, "j_password": VMANAGE_PASS},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()

    # Token
    r = s.get(
        base + "/dataservice/client/token",
        headers={"Accept": "application/json", "Referer": base + "/"},
        timeout=30,
    )
    r.raise_for_status()
    raw = r.text.strip()

    token = raw
    try:
        j = r.json()
        token = j.get("token") or j.get("X-XSRF-TOKEN") or raw
    except Exception:
        pass

    s.headers.update(
        {
            "X-XSRF-TOKEN": token,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "Referer": base + "/",
        }
    )

    logger.info("vManage login OK, token length=%d", len(token))
    return s, base


def vm_get_dpl_items(session: requests.Session, base: str) -> list[dict]:
    """Return list of all Data Prefix Lists (template/policy/list/dataprefix)."""
    logger.info("Fetching existing Data Prefix Lists...")
    r = session.get(base + "/dataservice/template/policy/list/dataprefix", timeout=30)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        return data.get("data", []) or []
    return data or []


def vm_update_dpl(session: requests.Session, base: str, list_id: str, name: str, cidrs: list[str]) -> None:
    """Update an existing Data Prefix List."""
    url = f"{base}/dataservice/template/policy/list/dataprefix/{list_id}"
    payload = {
        "name": name,
        "type": "dataPrefix",
        "entries": [{"ipPrefix": c} for c in cidrs],
    }
    r = session.put(url, json=payload, timeout=60)
    try:
        r.raise_for_status()
    except Exception as e:
        logger.error("Update failed for list %s (%s): %s", name, list_id, r.text[:400])
        raise e


def vm_create_dpl(session: requests.Session, base: str, name: str, cidrs: list[str]) -> str:
    """Create a new Data Prefix List, return its listId/uuid."""
    url = f"{base}/dataservice/template/policy/list/dataprefix"
    payload = {
        "name": name,
        "type": "dataPrefix",
        "entries": [{"ipPrefix": c} for c in cidrs],
    }
    r = session.post(url, json=payload, timeout=60)
    try:
        r.raise_for_status()
    except Exception as e:
        logger.error("Create failed for list %s: %s", name, r.text[:400])
        raise e

    # Response often contains {'listId': '...'} or similar
    try:
        data = r.json()
    except Exception:
        data = {}
    list_id = (
        data.get("listId")
        or data.get("id")
        or data.get("uuid")
        or data.get("data", {}).get("listId")
    )
    if not list_id:
        logger.warning("Create DPL %s: no listId in response, raw=%s", name, r.text[:300])
    return list_id or ""


def backup_dpl_json(dpl_item: dict, backup_dir: str, name: str) -> str:
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(backup_dir, f"{name}-{ts}.json")
    try:
        with open(path, "w") as f:
            json.dump(dpl_item, f, indent=2)
        logger.info("Backup written to %s", path)
    except Exception as e:
        logger.warning("Failed to write backup %s: %s", path, e)
    return path


# -----------------------------------------------------------------------------
#  Main Sync Logic
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Sync Zscaler IPs into Cisco vManage DPLs")
    ap.add_argument("--dry-run", action="store_true", help="Only show changes; do not push to vManage")
    args = ap.parse_args()

    # 1) Fetch & normalize Zscaler CIDRs
    try:
        new_cidrs = fetch_zscaler_prefixes(ZSCALER_JSON_URL, family=ZSCALER_FAMILY)
    except Exception as e:
        logger.error("Failed to fetch Zscaler list: %s", e)
        notify_teams("Zscaler Sync: Error", f"❌ Failed to fetch Zscaler list: {e}", success=False)
        return 1

    # 2) Delta vs cache
    old_cidrs = read_cache(CACHE_FILE)
    old_set = set(old_cidrs)
    new_set = set(new_cidrs)

    to_add = sorted(new_set - old_set)
    to_remove = sorted(old_set - new_set)

    logger.info("Diff -> add: %d, remove: %d", len(to_add), len(to_remove))

    if old_cidrs:
        pct_remove = (len(to_remove) / max(1, len(old_cidrs))) * 100.0
        if pct_remove > MAX_REMOVE_PERCENT:
            msg = f"Refusing change: removals {pct_remove:.2f}% > guard {MAX_REMOVE_PERCENT:.2f}%"
            logger.error(msg)
            notify_teams("Zscaler Sync: Blocked", f"❌ {msg}", success=False)
            return 2

    if args.dry_run:
        logger.info("[DRY-RUN] No changes will be pushed to vManage.")
        if to_add:
            logger.info("[DRY-RUN] To add (sample): %s%s", to_add[:20], " ..." if len(to_add) > 20 else "")
        if to_remove:
            logger.info("[DRY-RUN] To remove (sample): %s%s", to_remove[:20], " ..." if len(to_remove) > 20 else "")
        return 0

    # 3) Log in to vManage and pull existing DPLs
    try:
        session, base = vm_login()
        existing_items = vm_get_dpl_items(session, base)
    except Exception as e:
        logger.error("vManage connect/fetch failed: %s", e)
        notify_teams("Zscaler Sync: Error", f"❌ vManage connect failed: {e}", success=False)
        return 3

    # Find the "base" list if it exists (used in single-chunk case only)
    base_item = next((i for i in existing_items if i.get("name") == DPL_NAME), None)
    if base_item:
        logger.info("Found DPL '%s' with %d entries (ID=%s)",
                    DPL_NAME,
                    len(base_item.get("entries") or []),
                    base_item.get("listId") or base_item.get("id") or base_item.get("uuid"))
        backup_dpl_json(base_item, BACKUP_DIR, DPL_NAME)
    else:
        logger.info("DPL '%s' not found (will create if needed).", DPL_NAME)

    total = len(new_cidrs)
    logger.info("Total normalized Zscaler CIDRs to push: %d", total)

    # 4) Chunk logic
    max_chunk = max(1, ZSCALER_MAX_CHUNK)
    if total <= max_chunk:
        # Single list mode: update or create DPL_NAME only
        chunks = [(DPL_NAME, new_cidrs)]
    else:
        # Multi-chunk mode: create multiple lists DPL_NAME_01, DPL_NAME_02, ...
        num_chunks = math.ceil(total / max_chunk)
        logger.info("Large list (%d) → chunking into %d lists of ≤%d entries.",
                    total, num_chunks, max_chunk)
        chunks = []
        for i in range(num_chunks):
            start = i * max_chunk
            end = min(start + max_chunk, total)
            name = f"{DPL_NAME}_{i+1:02d}"
            chunks.append((name, new_cidrs[start:end]))

        logger.info("Chunk list names: %s", ", ".join(name for name, _ in chunks))
        logger.warning(
            "NOTE: In chunked mode, base DPL '%s' is NOT updated. "
            "Consumers should reference all '%s_XX' lists as needed.",
            DPL_NAME, DPL_NAME,
        )

    # 5) Apply chunks
    updated_lists = []
    for name, cidr_slice in chunks:
        item = next((i for i in existing_items if i.get("name") == name), None)
        if item:
            list_id = item.get("listId") or item.get("id") or item.get("uuid") or ""
            logger.info("Updating DPL '%s' (ID=%s) with %d entries", name, list_id, len(cidr_slice))
            backup_dpl_json(item, BACKUP_DIR, name)
            vm_update_dpl(session, base, list_id, name, cidr_slice)
            updated_lists.append((name, list_id, len(cidr_slice)))
        else:
            logger.info("Creating DPL '%s' with %d entries", name, len(cidr_slice))
            list_id = vm_create_dpl(session, base, name, cidr_slice)
            updated_lists.append((name, list_id, len(cidr_slice)))

    # 6) Cache new state & notify
    write_cache(CACHE_FILE, new_cidrs)
    logger.info("Zscaler sync completed successfully. Updated lists:")
    for name, list_id, cnt in updated_lists:
        logger.info("  - %s (ID=%s, entries=%d)", name, list_id or "<unknown>", cnt)

    notify_teams(
        "Zscaler Sync: Success",
        f"✅ Synced {total} CIDRs into {len(updated_lists)} DPL(s) on {VMANAGE_HOST}.",
        success=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
