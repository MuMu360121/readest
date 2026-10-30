#!/usr/bin/env python3
"""Patch the Android project that `pnpm tauri android init` generated (route A).

Route A = "do not restore the upstream tracked `gen/android`". That keeps the
package id and minSdk coming from `tauri.conf.json`, but it also loses the
upstream hand-maintained bits. This script restores the three things that have
to exist for the APK to be usable at all, and then *verifies* them:

  1. `missingDimensionStrategy("store"/"pen")` — otherwise Gradle cannot pick a
     variant for `:tauri-plugin-native-bridge` and the build dies with
     "The only attribute distinguishing these variants is 'VariantAttr'".
  2. `android:largeHeap="true"` in the manifest — the target devices are 512 MB
     e-readers; without it the WebView OOMs much earlier. Upstream tracked
     manifest carries it; the Tauri template does not.
  3. `minSdk = 25` and `applicationId = "app.reeed.reader"` — asserted, not
     written: they come from `tauri.conf.json` via `tauri android init`. If a
     future run goes back to restoring the tracked gradle (`minSdk = 26`,
     `com.bilingify.readest`), the assertions fail loudly instead of quietly
     shipping an APK that will not install on API 25.

Any failed assertion is a hard failure (exit 1). The script never prints
"nothing to do" and returns 0 on a project it has not verified.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "apps" / "readest-app" / "src-tauri" / "gen" / "android"
GRADLE = ANDROID / "app" / "build.gradle.kts"
MANIFEST = ANDROID / "app" / "src" / "main" / "AndroidManifest.xml"

EXPECT_MIN_SDK = "minSdk = 25"
EXPECT_APP_ID = 'applicationId = "app.reeed.reader"'
LARGE_HEAP = 'android:largeHeap="true"'

DIMENSIONS = (
    ("store", "foss"),
    ("pen", "genericPen"),
)


def _inject(text: str, anchor: str, payload: str) -> str:
    """Insert `payload` right after the line that opens `anchor`."""
    idx = text.find(anchor)
    if idx < 0:
        return text
    insert_at = text.find("\n", idx) + 1
    return text[:insert_at] + payload + text[insert_at:]


def patch_gradle(text: str) -> tuple[str, list[str]]:
    """Add the missing flavour strategies; report which dimensions were added."""
    missing = [(dim, default) for dim, default in DIMENSIONS
               if f'missingDimensionStrategy("{dim}"' not in text]
    if not missing:
        return text, []
    payload = (
        "        // Reeed: match the flavours declared by tauri-plugin-native-bridge,\n"
        "        // otherwise Gradle cannot resolve its variant (VariantAttr ambiguity).\n"
    )
    payload += "".join(
        f'        missingDimensionStrategy("{dim}", '
        f'project.findProperty("{dim}Flavor")?.toString() ?: "{default}")\n'
        for dim, default in missing
    )
    return _inject(text, "defaultConfig {", payload), [dim for dim, _ in missing]


def patch_manifest(text: str) -> tuple[str, bool]:
    """Add `android:largeHeap="true"` to <application>; idempotent."""
    if LARGE_HEAP in text:
        return text, False
    match = re.search(r"<application\b[^>]*>", text, re.S)
    if match is None:
        return text, False
    tag = match.group(0)
    new_tag = tag[:-1].rstrip() + f"\n        {LARGE_HEAP}>"
    return text[: match.start()] + new_tag + text[match.end():], True


LEGACY_PACKAGING = "useLegacyPackaging = true"


def patch_packaging(text: str) -> tuple[str, bool]:
    """Make the installer extract the native libs instead of mmap-ing the APK.

    The release package carries a 47.5 MiB STORED libreadestlib.so and
    `android:extractNativeLibs="false"`, so the loader maps it out of the APK.
    On a container-style Android (the Kindle build) that mmap can be refused and
    the process dies at startup with UnsatisfiedLinkError. Setting
    `packaging { jniLibs { useLegacyPackaging = true } }` goes back to extracting
    the .so into /data/app/<pkg>/lib. It costs ~50 MiB of /data, which is why it
    is an opt-in switch and not the default.
    """
    if LEGACY_PACKAGING in text:
        return text, False
    payload = (
        "    // Reeed: extract jniLibs on install instead of mmap-ing the APK.\n"
        "    // A 47.5 MiB STORED .so plus extractNativeLibs=false dies on\n"
        "    // container-style Android with UnsatisfiedLinkError.\n"
        "    packaging {\n"
        "        jniLibs {\n"
        f"            {LEGACY_PACKAGING}\n"
        "        }\n"
        "    }\n"
    )
    injected = _inject(text, "android {", payload)
    return injected, injected != text


def main() -> int:
    problems = []
    for path in (GRADLE, MANIFEST):
        if not path.exists():
            problems.append(f"missing file: {path}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    gradle = GRADLE.read_text(encoding="utf-8")
    gradle, added = patch_gradle(gradle)
    if added:
        GRADLE.write_text(gradle, encoding="utf-8")
        print(f"injected missingDimensionStrategy for: {', '.join(added)}")

    manifest = MANIFEST.read_text(encoding="utf-8")
    manifest, added_heap = patch_manifest(manifest)
    if added_heap:
        MANIFEST.write_text(manifest, encoding="utf-8")
        print(f"injected {LARGE_HEAP}")

    # Opt-in: extract jniLibs on install (see patch_packaging for the why).
    # The switch must live on the step that runs THIS script, not on an earlier
    # step: the env var is read here, and nowhere else.
    legacy = os.environ.get("REEED_LEGACY_PACKAGING") == "1"
    if legacy:
        gradle = GRADLE.read_text(encoding="utf-8")
        gradle, added_packaging = patch_packaging(gradle)
        if added_packaging:
            GRADLE.write_text(gradle, encoding="utf-8")
            print(f"injected {LEGACY_PACKAGING}")
        else:
            print(f"{LEGACY_PACKAGING} not injected (android block anchor missing "
                  f"or already present) — the assertion below decides")
    else:
        print(f"legacy packaging not requested (REEED_LEGACY_PACKAGING="
              f"{os.environ.get('REEED_LEGACY_PACKAGING', '<unset>')})")

    # Report the flavours that will actually be used, so the CI log records them.
    for dim, default in DIMENSIONS:
        env_key = f"ORG_GRADLE_PROJECT_{dim}Flavor"
        source = f"env {env_key}" if os.environ.get(env_key) else "script default"
        print(f"flavour {dim}={os.environ.get(env_key, default)} ({source})")

    # Hard assertions: a route change or a template change must fail the job.
    checks = (
        (GRADLE, EXPECT_MIN_SDK, "regenerated gradle did not take tauri.conf minSdkVersion"),
        (GRADLE, EXPECT_APP_ID, "regenerated gradle did not take tauri.conf identifier"),
        (GRADLE, 'missingDimensionStrategy("store"', "store dimension not injected"),
        (GRADLE, 'missingDimensionStrategy("pen"', "pen dimension not injected"),
        (MANIFEST, LARGE_HEAP, "largeHeap missing from the generated manifest"),
    )
    checks = list(checks)
    if legacy:
        # Requested but not applied is worse than not requested: the job would
        # publish an APK labelled "extracted-libs" that still loads in place.
        checks.append(
            (GRADLE, LEGACY_PACKAGING,
             "REEED_LEGACY_PACKAGING=1 but useLegacyPackaging was not injected"),
        )
    for path, needle, reason in checks:
        if needle not in path.read_text(encoding="utf-8"):
            problems.append(f"{reason}: {needle!r} not found in {path}")

    if problems:
        print("", file=sys.stderr)
        for problem in problems:
            print(f"ASSERTION FAILED: {problem}", file=sys.stderr)
        return 1

    print("verified: minSdk=25, applicationId=app.reeed.reader, largeHeap, both flavours"
          + (", useLegacyPackaging" if legacy else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
