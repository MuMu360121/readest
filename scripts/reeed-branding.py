#!/usr/bin/env python3
"""Rebrand the Readest source tree as Reeed for a self-built Android 7.1 APK.

What it changes (outward-facing identity only):
  - tauri.conf.json : productName / identifier / android minSdkVersion / updater endpoints
    (mainBinaryName is left alone: the generated Gradle project and the Rust lib
     name are wired to the upstream value, and changing it buys nothing visible)
  - public/manifest.json : PWA name, short_name, description
  - public/locales/*/translation.json : display values mentioning the upstream brand
  - data/icons/reeed.png + public/icon.png : a generated icon (the upstream artwork is not redistributable as our own)

What it deliberately keeps (AGPL-3.0 obligations):
  - LICENSE, copyright headers, and this note that the app was modified.
"""
import json
import struct
import sys
import zlib
from pathlib import Path

NEW_NAME = "Reeed"
NEW_BINARY = "reeed"
NEW_ID = "app.reeed.reader"
OLD_NAME = "Readest"
UPSTREAM_UPDATE_HOST = "readest.com"
PLACEHOLDER_ENDPOINT = "https://example.invalid/reeed/latest.json"
MIN_SDK = 25
# API 25 上 WebView 上限就是 119（Chrome 120 起不再支持 Android 7），
# 上游的 121 在目标设备上永远不可达，留着只会每次启动做一次无谓探测并
# 打一条会被误读成故障的 W/ 日志。
WEBVIEW_MIN_UPGRADE = 119
WEBVIEW_MIN_SUPPORTED = 111

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "readest-app"

changed = []


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    changed.append(str(path.relative_to(ROOT)))


def patch_tauri_conf() -> None:
    path = APP / "src-tauri" / "tauri.conf.json"
    conf = json.loads(path.read_text(encoding="utf-8"))
    conf["productName"] = NEW_NAME
    conf["identifier"] = NEW_ID
    conf.setdefault("bundle", {}).setdefault("android", {})["minSdkVersion"] = MIN_SDK

    plugins = conf.setdefault("plugins", {})
    webview_upgrade = plugins.get("webview-upgrade")
    if isinstance(webview_upgrade, dict):
        webview_upgrade["minUpgradeMajor"] = WEBVIEW_MIN_UPGRADE
        if "minSupportedMajor" in webview_upgrade:
            assert webview_upgrade["minSupportedMajor"] == WEBVIEW_MIN_SUPPORTED, (
                "minSupportedMajor 被上游改动，需重新评估 119 设备是否仍算支持"
            )

    updater = conf.get("plugins", {}).get("updater")
    if isinstance(updater, dict):
        # Never point a self-built fork at the upstream release feed.
        updater["endpoints"] = [PLACEHOLDER_ENDPOINT]
    write_json(path, conf)


def patch_manifest() -> None:
    path = APP / "public" / "manifest.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["name"] = NEW_NAME
    data["short_name"] = NEW_NAME
    desc = str(data.get("description", ""))
    if OLD_NAME in desc:
        data["description"] = desc.replace(OLD_NAME, NEW_NAME)
    write_json(path, data)


def patch_locales() -> int:
    """Replace the brand in display values only; keys are lookup strings and must stay."""
    count = 0
    locales = APP / "public" / "locales"
    if not locales.is_dir():
        return 0
    for path in sorted(locales.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a broken locale file must not break the build
            print(f"skip {path}: {exc}", file=sys.stderr)
            continue

        def walk(node):
            if isinstance(node, str):
                return node.replace(OLD_NAME, NEW_NAME)
            if isinstance(node, list):
                return [walk(x) for x in node]
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            return node

        new = walk(data)
        if new != data:
            path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            count += 1
    return count


def make_icon(size: int = 1024) -> bytes:
    """A plain generated icon: dark field, light rounded square, hollow centre."""
    bg = (22, 24, 30, 255)
    fg = (124, 196, 158, 255)
    cx = cy = size / 2.0
    half = size * 0.30
    radius = size * 0.10
    rows = []
    for y in range(size):
        row = bytearray([0])  # PNG filter type 0
        for x in range(size):
            # rounded square mask
            dx = max(abs(x - cx) - (half - radius), 0.0)
            dy = max(abs(y - cy) - (half - radius), 0.0)
            inside_square = dx * dx + dy * dy <= radius * radius
            # hollow ring in the middle
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            ring = half * 0.34 <= dist <= half * 0.62
            row += bytes(fg if inside_square and not ring else bg)
        rows.append(bytes(row))

    raw = b"".join(rows)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def write_icons() -> None:
    png = make_icon()
    for rel in ("data/icons/reeed.png", "apps/readest-app/public/icon.png"):
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        changed.append(str(path.relative_to(ROOT)))


def main() -> int:
    patch_tauri_conf()
    patch_manifest()
    locale_files = patch_locales()
    write_icons()
    print("rebranded files:")
    for rel in changed:
        print(f"  {rel}")
    print(f"locale files updated: {locale_files}")
    conf = json.loads((APP / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    wu = (conf.get("plugins") or {}).get("webview-upgrade") or {}
    print(
        f"productName={NEW_NAME} identifier={NEW_ID} minSdk={MIN_SDK} "
        f"webview-upgrade={{minUpgradeMajor:{wu.get('minUpgradeMajor')}, "
        f"minSupportedMajor:{wu.get('minSupportedMajor')}}}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
