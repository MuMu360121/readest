#!/usr/bin/env python3
"""把 Reeed 崩溃诊断接进 tauri 生成的 Android 工程（幂等）。

做四件事，全部可重复执行：
  1. 拷贝 ReeedApplication.kt / CrashReport.kt / CrashActivity.kt 到
     <gen/android>/app/src/main/java/app/reeed/reader/
  2. <application> 上确保有且只有一个 android:name="app.reeed.reader.ReeedApplication"
     （已存在别的值 → 替换；已存在同值 → 跳过；没有 → 追加）
  3. </application> 前插入 CrashActivity 的 <activity>（独立 :crash 进程）
  4. <manifest> 下确保有 <queries>，并把 WebView/Chrome 候选包列进去
     （API 30+ 被包可见性挡住时，CrashReport 才读得到 versionName；API 25 上无副作用）

不碰：minSdk / applicationId / icon / 签名 / extractNativeLibs。
extractNativeLibs 不要写进 manifest —— AGP 会用它自己的 useLegacyPackaging 结果覆盖，
要排 in-place dlopen 分支请用 gradle 的 packaging { jniLibs { useLegacyPackaging = true } }。

用法（必须在 tauri android init 之后、build 之前调用）：
    python3 scripts/reeed-crashhandler/inject.py apps/readest-app/src-tauri/gen/android
"""

import os
import re
import shutil
import sys

PKG = "app.reeed.reader"
PKG_DIR = os.path.join("app", "src", "main", "java", *PKG.split("."))
MANIFEST = os.path.join("app", "src", "main", "AndroidManifest.xml")
APP_NAME_ATTR = 'android:name="%s.ReeedApplication"' % PKG

ACTIVITY_XML = (
    '\n        <activity\n'
    '            android:name="%s.CrashActivity"\n'
    '            android:process=":crash"\n'
    '            android:exported="false"\n'
    '            android:excludeFromRecents="true"\n'
    '            android:launchMode="singleTask"\n'
    '            android:theme="@android:style/Theme.DeviceDefault.NoActionBar.Fullscreen" />\n' % PKG
)

QUERY_PACKAGES = [
    "com.android.webview",
    "com.google.android.webview",
    "com.google.android.webview.beta",
    "com.google.android.webview.dev",
    "com.android.chrome",
    "com.huawei.webview",
]

HERE = os.path.dirname(os.path.abspath(__file__))
KT_FILES = ["ReeedApplication.kt", "CrashReport.kt", "CrashActivity.kt"]


def fail(msg):
    sys.stderr.write("CORE CRASHHANDLER FAIL: %s\n" % msg)
    sys.exit(1)


def copy_sources(gen_root):
    dest = os.path.join(gen_root, PKG_DIR)
    os.makedirs(dest, exist_ok=True)
    for name in KT_FILES:
        src = os.path.join(HERE, name)
        if not os.path.isfile(src):
            fail("missing source %s" % src)
        shutil.copyfile(src, os.path.join(dest, name))
        print("copied %s -> %s" % (name, os.path.relpath(os.path.join(dest, name), gen_root)))


def patch_application_name(text):
    """<application ...> 里保证恰好一个 android:name，值为我们的 Application。"""
    m = re.search(r"<application\b[^>]*>", text, re.S)
    if not m:
        fail("no <application> element in manifest")
    tag = m.group(0)

    existing = re.findall(r'android:name\s*=\s*"[^"]*"', tag)
    if len(existing) > 1:
        fail("<application> already has %d android:name attributes: %s" % (len(existing), existing))

    if existing and existing[0] == APP_NAME_ATTR:
        print("manifest: ReeedApplication already registered, skip")
        return text

    if existing:
        new_tag = tag.replace(existing[0], APP_NAME_ATTR, 1)
        print("manifest: replaced existing %s with ReeedApplication" % existing[0])
    else:
        new_tag = tag[:-1].rstrip() + " " + APP_NAME_ATTR + ">"
        print("manifest: added android:name=ReeedApplication")

    return text[: m.start()] + new_tag + text[m.end():]


def patch_activity(text):
    if "CrashActivity" in text:
        print("manifest: CrashActivity already present, skip")
        return text
    if "</application>" not in text:
        fail("no </application> closing tag in manifest")
    return text.replace("</application>", ACTIVITY_XML + "    </application>", 1)


def patch_queries(text):
    missing = [p for p in QUERY_PACKAGES if 'android:name="%s"' % p not in text]
    if not missing:
        print("manifest: <queries> already covers webview packages, skip")
        return text

    lines = "".join('        <package android:name="%s" />\n' % p for p in missing)

    # 自闭合的 <queries /> 也得认：只按成对标签匹配会漏掉它，
    # 然后插入第二个 <queries> —— aapt2 直接报重复元素，白烧一轮构建。
    m0 = re.search(r"<queries\b[^>]*?/>", text, re.S)
    if m0:
        block = "<queries>\n%s    </queries>" % lines
        print("manifest: expanded self-closing <queries> with %d package(s)" % len(missing))
        return text[: m0.start()] + block + text[m0.end():]

    m = re.search(r"<queries\b[^>]*>\s*</queries>", text, re.S)
    if m:
        merged = "<queries>\n%s    </queries>" % lines
        print("manifest: extended existing <queries> with %d package(s)" % len(missing))
        return text[: m.start()] + merged + text[m.end():]

    m2 = re.search(r"<queries\b[^>]*>.*?</queries>", text, re.S)
    if m2:
        block = m2.group(0)
        inserted = block.replace("</queries>", lines + "    </queries>", 1)
        print("manifest: added %d package(s) into existing <queries>" % len(missing))
        return text[: m2.start()] + inserted + text[m2.end():]

    if "<manifest" not in text:
        fail("no <manifest> element in manifest")
    end = text.index(">", text.index("<manifest")) + 1
    block = "\n    <queries>\n%s    </queries>" % lines
    print("manifest: created <queries> with %d package(s)" % len(missing))
    return text[:end] + block + text[end:]


def patch_manifest(gen_root):
    path = os.path.join(gen_root, MANIFEST)
    if not os.path.isfile(path):
        fail("manifest not found: %s (did tauri android init run?)" % path)

    with open(path, encoding="utf-8") as fh:
        original = fh.read()

    text = patch_application_name(original)
    text = patch_activity(text)
    text = patch_queries(text)

    if text != original:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("manifest: patched %s" % path)
    return text


def assert_patched(text):
    problems = []

    m = re.search(r"<application\b[^>]*>", text, re.S)
    if not m:
        problems.append("no <application> element")
    else:
        names = re.findall(r'android:name\s*=\s*"[^"]*"', m.group(0))
        if names != [APP_NAME_ATTR]:
            problems.append("application android:name is %s, expected exactly [%s]" % (names, APP_NAME_ATTR))

    if 'android:name="%s.CrashActivity"' % PKG not in text:
        problems.append("CrashActivity element missing")

    app_start = text.find("<application")
    app_end = text.find("</application>")
    act_at = text.find("CrashActivity")
    if not (app_start < act_at < app_end):
        problems.append("CrashActivity is outside <application>")

    for p in QUERY_PACKAGES:
        if 'android:name="%s"' % p not in text:
            problems.append("queries missing package %s" % p)

    if problems:
        fail("; ".join(problems))
    print("ASSERTIONS: ReeedApplication(unique) + CrashActivity(inside application) + queries(6) OK")


def main():
    if len(sys.argv) != 2:
        fail("usage: inject.py <path-to-src-tauri/gen/android>")
    gen_root = sys.argv[1]
    if not os.path.isdir(gen_root):
        fail("not a directory: %s" % gen_root)
    copy_sources(gen_root)
    text = patch_manifest(gen_root)
    assert_patched(text)


if __name__ == "__main__":
    main()
