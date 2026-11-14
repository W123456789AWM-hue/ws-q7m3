package com.example.ai_mind

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import androidx.core.content.FileProvider
import java.io.File

class MainActivity : FlutterActivity() {

    companion object {
        // 进程内共享一个 FlutterEngine：用户从“最近任务”划掉界面时，
        // Dart 里的录音/上传逻辑不随 Activity 销毁，继续在前台服务保护下运行。
        private var sharedEngine: FlutterEngine? = null
    }

    override fun provideFlutterEngine(context: Context): FlutterEngine {
        return sharedEngine ?: FlutterEngine(context.applicationContext).also {
            sharedEngine = it
        }
    }

    override fun shouldDestroyEngineWithHost(): Boolean = false

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "ai_mind/android")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "startService" -> {
                        requestNotificationPermissionIfNeeded()
                        try {
                            RecordingService.start(applicationContext)
                            result.success(true)
                        } catch (e: Exception) {
                            result.error("SERVICE", e.message, null)
                        }
                    }
                    "stopService" -> {
                        RecordingService.stop(applicationContext)
                        result.success(true)
                    }
                    "isIgnoringBatteryOptimizations" -> {
                        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                        result.success(pm.isIgnoringBatteryOptimizations(packageName))
                    }
                    "requestIgnoreBatteryOptimizations" -> {
                        try {
                            startActivity(
                                Intent(
                                    Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                    Uri.parse("package:$packageName")
                                )
                            )
                            result.success(true)
                        } catch (e: Exception) {
                            result.error("BATTERY", e.message, null)
                        }
                    }
                    "abi" -> result.success(Build.SUPPORTED_ABIS.firstOrNull() ?: "arm64-v8a")
                    "installApk" -> {
                        // 在线更新：把下载好的 APK 交给系统安装界面（用户点“安装”）
                        try {
                            if (Build.VERSION.SDK_INT >= 26 && !packageManager.canRequestPackageInstalls()) {
                                startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:$packageName")))
                                result.success("need_permission")
                            } else {
                                val file = File(call.argument<String>("path")!!)
                                val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
                                startActivity(Intent(Intent.ACTION_VIEW).apply {
                                    setDataAndType(uri, "application/vnd.android.package-archive")
                                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                                })
                                result.success("ok")
                            }
                        } catch (e: Exception) {
                            result.error("INSTALL", e.message, null)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2001)
        }
    }
}
