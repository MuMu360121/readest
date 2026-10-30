package app.reeed.reader

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 崩溃报告的环境信息 + 落盘。
 *
 * WebView 版本是这里最重要的一行：API 25 上 WebView.getCurrentWebViewPackage()（API 26+）不可用，
 * 所以改为直接查候选包。没有 adb 也能拿到实际生效的内核主版本，这正是当前最大的未知数。
 *
 * 落盘顺序：外部私有目录 → 内部 filesDir → cacheDir。三个都试，返回真正写成功的那条路径。
 * Kindle 容器里 getExternalFilesDir(null) 经常是 null 或不可写，只写外部等于静默丢证据。
 */
object CrashReport {

    private val CANDIDATES = listOf(
        "com.google.android.webview",
        "com.google.android.webview.beta",
        "com.google.android.webview.dev",
        "com.android.webview",
        "com.android.chrome",
        "com.huawei.webview",
    )

    fun describe(ctx: Context): String {
        val sb = StringBuilder()
        sb.append("Reeed crash report  ")
        sb.append(SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date()))
        sb.append("\ndevice=").append(android.os.Build.MANUFACTURER).append(' ')
            .append(android.os.Build.MODEL)
        sb.append("\nbuild=").append(android.os.Build.DISPLAY)
        sb.append("\nsdk=").append(android.os.Build.VERSION.SDK_INT)
            .append("  release=").append(android.os.Build.VERSION.RELEASE)
        sb.append("\nabis=").append(android.os.Build.SUPPORTED_ABIS.joinToString(","))
        sb.append("\nwebview: ").append(webViewVersions(ctx))
        sb.append("\n")
        return sb.toString()
    }

    @Suppress("DEPRECATION")
    fun webViewVersions(ctx: Context): String {
        val found = ArrayList<String>()
        for (pkg in CANDIDATES) {
            try {
                val info = ctx.packageManager.getPackageInfo(pkg, 0)
                val enabled = info.applicationInfo?.enabled ?: false
                found.add("$pkg=${info.versionName} enabled=$enabled")
            } catch (e: Throwable) {
                // 没装、或被包可见性挡住；两个结果都只是"看不到"，不要当成"不存在"。
            }
        }
        if (found.isEmpty()) return "none-visible（未装或被 queries 可见性挡住）"
        return found.joinToString(" | ")
    }

    /** 外部 → 内部 filesDir → cache，逐个探测；null 表示该级不可用。 */
    private fun candidateDirs(ctx: Context): List<File> {
        val dirs = ArrayList<File>()
        var external: File? = null
        try {
            external = ctx.getExternalFilesDir(null)
        } catch (t: Throwable) {
            external = null
        }
        if (external != null) dirs.add(external)

        try {
            val internal = ctx.filesDir
            if (internal != null) dirs.add(internal)
        } catch (t: Throwable) {
            // 内部存储理论上一定存在，拿不到就跳过
        }

        try {
            val cache = ctx.cacheDir
            if (cache != null) dirs.add(cache)
        } catch (t: Throwable) {
            // 同上
        }
        return dirs
    }

    /** 按 外部 → 内部 → cache 顺序尝试，返回真正写成的那条绝对路径；全失败才返回 null。 */
    fun write(ctx: Context, text: String): String? {
        val dirs = candidateDirs(ctx)

        for (dir in dirs) {
            val path = try {
                if (!dir.exists()) dir.mkdirs()
                val f = File(dir, "crash.txt")
                f.writeText(text)
                if (f.exists() && f.length() > 0L) f.absolutePath else null
            } catch (t: Throwable) {
                null
            }
            if (path != null) return path
        }
        return null
    }

    /** 与 write() 同顺序读取，供 :crash 进程在拿不到 Intent extra 时回读。 */
    fun read(ctx: Context): String? {
        val dirs = candidateDirs(ctx)

        for (dir in dirs) {
            try {
                val f = File(dir, "crash.txt")
                if (f.exists() && f.length() > 0L) return f.readText()
            } catch (t: Throwable) {
                // 换下一个目录
            }
        }
        return null
    }
}
