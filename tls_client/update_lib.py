from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from .utils import get_dependency_filename

# Axen Go fork (bogdanfinn main + chrome_150). Not bogdanfinn release assets.
PINNED_GO_VERSION = "latest"
GITHUB_TAG_API_URL = "https://api.github.com/repos/QubitLabsAU/tls-client/releases/tags/{tag}"

LOCAL_VERSION_FILE = os.path.join(os.path.dirname(__file__), "dependencies/version.txt")
DOWNLOAD_DIR = os.path.dirname(LOCAL_VERSION_FILE)
CHECK_INTERVAL = timedelta(hours=24)

CURRENT_DEPENDENCY_FILENAME = get_dependency_filename()


def _auth_headers() -> dict:
    headers = {"Accept": "application/octet-stream"}
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers


def _get_release_by_tag(session: requests.Session, tag: str) -> tuple[Any, str | None]:
    headers = {}
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    url = GITHUB_TAG_API_URL.format(tag=tag)
    response = session.get(url, headers=headers)
    response.raise_for_status()
    return response.json(), response.headers.get("Etag")


def read_local_version() -> Optional[Dict[str, str]]:
    if os.path.exists(LOCAL_VERSION_FILE):
        with open(LOCAL_VERSION_FILE, "r") as f:
            lines = f.read().splitlines(False)
            if len(lines) >= 3:
                return {
                    "version": lines[0],
                    "last_modified": lines[1],
                    "last_check": lines[2],
                }
    return None


def save_local_version(version: str, last_modified: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with open(LOCAL_VERSION_FILE, "w") as f:
        f.write(f"{version}\n{last_modified}\n{now}")


def _download_file(session: requests.Session, url: str, dest_path: str) -> None:
    # Private release assets need auth; follow redirects to S3/etc.
    response = session.get(url, headers=_auth_headers(), allow_redirects=True)
    response.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(response.content)


def _should_check_update() -> bool:
    # ponytail: if the platform lib already exists, skip network unless forced.
    lib_path = os.path.join(DOWNLOAD_DIR, CURRENT_DEPENDENCY_FILENAME or "")
    if CURRENT_DEPENDENCY_FILENAME and os.path.isfile(lib_path):
        if os.getenv("AXEN_TLS_FORCE_UPDATE") != "1":
            return False

    local_version_info = read_local_version()
    if not local_version_info or "last_check" not in local_version_info:
        return True
    last_check = datetime.fromisoformat(local_version_info["last_check"])
    return datetime.now(timezone.utc) - last_check > CHECK_INTERVAL


def _download_release(
    session: requests.Session,
    release: dict,
    version: str,
    etag: str,
) -> None:
    assets = release["assets"]
    dependency = CURRENT_DEPENDENCY_FILENAME.rsplit(".", 1)[0]
    for asset in assets:
        if asset["name"].startswith(dependency):
            # API asset URL works for private repos with token
            download_url = asset.get("url") or asset["browser_download_url"]
            dest_path = os.path.join(DOWNLOAD_DIR, CURRENT_DEPENDENCY_FILENAME)
            _download_file(session, download_url, dest_path)
            print(f"Downloaded {CURRENT_DEPENDENCY_FILENAME} " f"from {download_url}")
            break
    else:
        print(f"Could not find asset for {CURRENT_DEPENDENCY_FILENAME}")
        return

    save_local_version(version, etag or "")
    print(f"Installed Go library {version}")


def update_lib() -> None:
    if not CURRENT_DEPENDENCY_FILENAME:
        return

    if not _should_check_update():
        return

    local_version_info = read_local_version()
    if local_version_info and local_version_info["version"] == PINNED_GO_VERSION:
        lib_path = os.path.join(DOWNLOAD_DIR, CURRENT_DEPENDENCY_FILENAME)
        if os.path.isfile(lib_path):
            save_local_version(
                PINNED_GO_VERSION,
                local_version_info.get("last_modified", ""),
            )
            return

    print(f"Installing Go library {PINNED_GO_VERSION}")

    session = requests.Session()
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    release, etag = _get_release_by_tag(session, PINNED_GO_VERSION)
    _download_release(session, release, PINNED_GO_VERSION, etag)


if __name__ == "__main__":
    update_lib()
