#!/usr/bin/env python3
"""Fix the Gradle variant-ambiguity that breaks a Tauri-generated Android project.

`pnpm tauri android init` regenerates `gen/android/app/build.gradle.kts` from the
Tauri template. That template does not know about the product flavors declared by
`tauri-plugin-native-bridge` (store: foss/googleplay, pen: genericPen/booxPen), so
Gradle cannot pick a variant for `:tauri-plugin-native-bridge` and the build dies:

    Could not resolve project :tauri-plugin-native-bridge
    The only attribute distinguishing these variants is ... VariantAttr

Upstream keeps a hand-maintained `gen/android/app/build.gradle.kts` carrying
`missingDimensionStrategy(...)` for both dimensions (and their release workflow
restores it with `git checkout .`). We do not restore the file — we only inject the
two lines it needs, so the regenerated project keeps our own minSdkVersion and
package id.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADLE = ROOT / "apps" / "readest-app" / "src-tauri" / "gen" / "android" / "app" / "build.gradle.kts"

INJECT = (
    '        // Reeed: match the flavors declared by tauri-plugin-native-bridge,\n'
    '        // otherwise Gradle cannot resolve its variant (VariantAttr ambiguity).\n'
    '        missingDimensionStrategy("store", project.findProperty("storeFlavor")?.toString() ?: "foss")\n'
    '        missingDimensionStrategy("pen", project.findProperty("penFlavor")?.toString() ?: "genericPen")\n'
)


def main() -> int:
    if not GRADLE.exists():
        print(f"gradle file not found: {GRADLE}", file=sys.stderr)
        return 1
    text = GRADLE.read_text(encoding="utf-8")
    if "missingDimensionStrategy" in text:
        print("missingDimensionStrategy already present; nothing to do")
        return 0
    marker = "defaultConfig {"
    idx = text.find(marker)
    if idx < 0:
        print(f"`{marker}` not found in {GRADLE}", file=sys.stderr)
        return 1
    insert_at = text.find("\n", idx) + 1
    patched = text[:insert_at] + INJECT + text[insert_at:]
    GRADLE.write_text(patched, encoding="utf-8")
    print("injected missingDimensionStrategy after defaultConfig {")
    for line in patched.splitlines():
        if "missingDimensionStrategy" in line or "minSdk" in line or "applicationId" in line or "namespace" in line:
            print("  ", line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
