# Reeed 崩溃诊断接入（Android / API 25）

目的：启动即崩、又没有 adb 的情况下，让设备自己把栈显示在屏幕上，同时顺带把**实际生效的 WebView 包与版本**打出来。

## 文件

| 文件 | 作用 |
|---|---|
| `ReeedApplication.kt` | `attachBaseContext` 装 `Thread.setDefaultUncaughtExceptionHandler`；写 `crash.txt`；拉起 `:crash` 进程的诊断 Activity |
| `CrashReport.kt` | 环境信息（设备/SDK/ABI/**WebView 包与版本**）+ 落盘（外部 → `filesDir` → `cacheDir` 三级回退，返回真实路径） |
| `CrashActivity.kt` | 全屏 TextView 显示栈 + 「分享诊断文本」按钮 |
| `inject.py` | 幂等注入：拷 `.kt`；给 `<application>` 保证**有且只有一个** `android:name`（已有别的值则替换，不追加）；在 `<application>` 内插入 `CrashActivity`；给 `<manifest>` 补 `<queries>`（6 个 WebView/Chrome 候选包，API 30+ 读 versionName 需要） |

## 接入位置（顺序是硬约束）

必须在 `tauri android init` **之后**、`tauri android build` **之前**，且排在 flavour/`largeHeap` 那个补丁脚本之后（两边都会改 manifest，顺序反了不会互相破坏，但断言跑在最后更干净）：

```bash
python3 scripts/reeed-crashhandler/inject.py apps/readest-app/src-tauri/gen/android
```

成功输出末行：

```
ASSERTIONS: ReeedApplication + CrashActivity present and inside <application>
```

## 已验证 / 未验证

- **已跑过**：`inject.py` 对三种 manifest 形态各连跑两次（共 6 次），全部 `exit 0`：
  1. tauri 默认形态（无 `android:name`、无 `<queries>`）→ 追加属性 + 新建 `<queries>`；
  2. 已有 `android:name="com.other.LegacyApp"`（别的插件写过）→ **替换**为我们的，不会出现两个属性；
  3. 已是我们的 Application 且已有 `<queries>`（只含 1 个包）→ 只补其余 5 个包，不重复。
  每个 fixture 注入后 `xml.etree` 解析通过、第二次运行全部 skip；`python3 -m py_compile inject.py` 通过；三个 `.kt` 括号配对与跨文件符号引用交叉核对通过。
- **未跑过**：本机无 `kotlinc` / Android SDK，**Kotlin 未编译**；`<queries>` 插在 `<uses-permission>` 之前（manifest 子元素顺序对 aapt2 无强制要求，但真构建若有告警以构建日志为准）。
- **没跑过**：本机没有 `kotlinc`、没有 Android SDK，**Kotlin 未编译**。第一次真编译由 CI 承担；如果编译失败，报错会出现在 `build release apk` 步，不会污染产物。

## 设备上的三种结果，含义完全不同

1. **出现白屏页 + 大段栈** → Java 层未捕获异常拿全了。第一件事看它顶部的 `webview:` 行（实际内核版本），第二件事把文本「分享」出来。
2. **仍然只有系统「已停止运行」，没有诊断页** → 说明不是 Java 层未捕获异常，可能是：native 崩（`SIGSEGV`，handler 收不到）、被系统低内存杀掉（zram 512MB / `libreadestlib.so` 47.5 MiB）、或崩在 `Application` 实例化之前。此时只能走 `logcat -b crash` / tombstone。
3. **诊断页出现但内容是空的** → `startActivity` 失败（`NEW_TASK` 已加；容器可能拦），此时看 `/sdcard/Android/data/app.reeed.reader/files/crash.txt`。

## 不做的事

- **不改 `extractNativeLibs`**。manifest 里写这个属性会被 AGP 的 `packaging { jniLibs { useLegacyPackaging } }` 结果覆盖；要排除 in-place `dlopen` 分支，请用 gradle 的 `useLegacyPackaging = true`，别在 manifest 里加。
- 不动 `minSdk` / `applicationId` / 签名 / icon。
- 不装第二套崩溃上报 SDK。
