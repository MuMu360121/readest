package app.reeed.reader

import android.app.Application
import android.content.Context
import android.content.Intent
import java.io.PrintWriter
import java.io.StringWriter

/**
 * Reeed 诊断用 Application。
 *
 * 为什么挂在 attachBaseContext 而不是 onCreate：
 * 崩溃可能发生在 androidx.startup 的 ContentProvider.onCreate 阶段
 * （Tauri 插件的 Initializer 就是走这条路），那时 Application.onCreate 还没跑，
 * 装在那里的 handler 收不到。attachBaseContext 早于所有 provider，是能覆盖到的最早点。
 *
 * 装的是"默认"未捕获异常处理器，不是 try/catch：
 * 只能拿到已经在往上的异常，拿到后写文件 + 拉起 :crash 进程的诊断 Activity。
 * 注意：native 崩溃（SIGSEGV）和系统直接 kill（低内存）不会走这里，那种情况只能靠 logcat。
 */
class ReeedApplication : Application() {

    override fun attachBaseContext(base: Context) {
        super.attachBaseContext(base)

        // :crash 进程里不再装 handler，否则诊断页自己崩一次就会递归拉自己。
        if (processSuffix() == "crash") return

        val app = this
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            try {
                val sw = StringWriter()
                throwable.printStackTrace(PrintWriter(sw))
                val report = CrashReport.describe(app) +
                    "\n=== thread ===\n" + thread.name +
                    "\n\n=== stack ===\n" + sw.toString() +
                    "\n\n=== raw StackTraceElement ===\n" +
                    throwable.stackTrace.joinToString("\n") { it.toString() }

                // 先落盘再拉界面：:crash 进程万一被 ROM 一起收走，文件还在。
                val path = CrashReport.write(app, report)

                // 同一份内容再打一次 logcat：万一只剩日志通道（或有 logcat 抓取），也能拿到。
                android.util.Log.e("REED_CRASH", report)

                val intent = Intent(app, CrashActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
                    addFlags(Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS)
                    // Intent 走 binder，有 1MB 上限；栈可能很长，extra 截到 60k 字符，完整内容在 crash.txt。
                    val extra = if (report.length > 60000) {
                        report.substring(0, 60000) + "\n...[truncated in extra, full text in crash.txt]"
                    } else {
                        report
                    }
                    putExtra(CrashActivity.EXTRA_REPORT, extra)
                    putExtra(CrashActivity.EXTRA_PATH, path)
                }
                app.startActivity(intent)

                // 给 :crash 进程一点时间把首帧画出来，再交给系统去杀主进程。
                Thread.sleep(1500)
            } catch (t: Throwable) {
                // 诊断路径自己出错也必须吞掉，否则会把原始崩溃盖掉。
            } finally {
                if (previous != null) {
                    previous.uncaughtException(thread, throwable)
                } else {
                    android.os.Process.killProcess(android.os.Process.myPid())
                }
            }
        }
    }

    /** 取进程名前缀之后的段：:crash 返回 "crash"，主进程返回 ""。API 25 没有 getProcessName()。 */
    private fun processSuffix(): String {
        return try {
            val raw = java.io.File("/proc/self/cmdline").readText()
            val name = raw.trim('\u0000').substringBefore('\u0000')
            name.substringAfter(':', "")
        } catch (t: Throwable) {
            ""
        }
    }
}
