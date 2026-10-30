package app.reeed.reader

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.text.method.ScrollingMovementMethod
import android.util.TypedValue
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * 崩溃现场界面（运行在独立的 :crash 进程里，manifest 里 android:process=":crash"）。
 *
 * 独立进程是关键：主进程被杀掉、甚至被 ROM 连带清掉时，这个 Activity 仍能把栈显示出来。
 * 界面上不做任何业务依赖，只有 TextView + 分享按钮，避免"诊断页自己又崩一次"。
 */
class CrashActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val report = intent.getStringExtra(EXTRA_REPORT) ?: CrashReport.read(this) ?: "no report captured"
        val path = intent.getStringExtra(EXTRA_PATH)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            setPadding(16, 16, 16, 16)
        }

        val body = TextView(this).apply {
            text = buildString {
                append(report)
                append("\n\n=== crash.txt ===\n")
                append(path ?: "未写出（无外部存储或无权限）")
                append("\n\n把这段文字分享出来，或直接截图。")
            }
            setTextColor(Color.BLACK)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setTextIsSelectable(true)
            movementMethod = ScrollingMovementMethod()
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }

        val share = Button(this).apply {
            text = "分享诊断文本"
            setOnClickListener {
                val send = Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_SUBJECT, "Reeed crash")
                    putExtra(Intent.EXTRA_TEXT, report)
                }
                startActivity(Intent.createChooser(send, "分享"))
            }
        }

        root.addView(body)
        root.addView(share)
        setContentView(root)
    }

    companion object {
        const val EXTRA_REPORT = "app.reeed.reader.CRASH_REPORT"
        const val EXTRA_PATH = "app.reeed.reader.CRASH_PATH"
    }
}
