package com.clipblitz.standalone;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.view.ViewGroup;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * ClipBlitz Studio, standing on its own: this app boots CPython, loads the real
 * clipblitz engine, starts the engine's own HTTP server on the phone and then shows the
 * studio UI from 127.0.0.1. No PC, no LAN, no companion.
 *
 * The activity is deliberately a thin shell around a thick engine: everything that used to
 * happen on the desktop happens in this process. If the engine cannot come up, the screen
 * says so in full rather than showing a blank WebView.
 */
public class MainActivity extends Activity {

    private static final String TAG = "ClipBlitzStandalone";
    private static final int PORT = 4390;

    private LinearLayout root;
    private WebView web;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(28), dp(20), dp(20));
        setContentView(root);
        say("boot", "Starting the engine on this device...\n\nCPython is bundled in the APK; "
                + "the first start copies it out and imports the studio.");
        new Thread(this::bootEngine, "clipblitz-boot").start();
    }

    /** Runs off the UI thread: Python start, engine import, server start, health poll. */
    private void bootEngine() {
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            Python py = Python.getInstance();
            String python = py.getModule("sys").get("version").toString();
            Log.i(TAG, "python: " + python);

            String filesDir = getFilesDir().getAbsolutePath();
            String dataDir = py.getModule("android_bootstrap")
                    .callAttr("start", PORT, filesDir).toString();
            Log.i(TAG, "engine data dir: " + dataDir);

            String health = poll("http://127.0.0.1:" + PORT + "/api/health", 90);
            if (health == null) {
                say("failed", "The engine started but /api/health never answered on port "
                        + PORT + ".\n\nPython: " + python + "\nData dir: " + dataDir
                        + "\n\nCheck `adb logcat -s clipblitz` for the Python traceback.");
                return;
            }
            Log.i(TAG, "health: " + health);
            showStudio(python, health);
        } catch (Throwable t) {
            Log.e(TAG, "engine boot failed", t);
            say("failed", "The engine did not start on this device.\n\n" + t);
        }
    }

    /** GET a URL until it answers 200, returning the body, or null after `seconds`. */
    private String poll(String url, int seconds) {
        for (int i = 0; i < seconds; i++) {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(2000);
                c.setReadTimeout(4000);
                if (c.getResponseCode() == 200) {
                    StringBuilder sb = new StringBuilder();
                    try (BufferedReader r = new BufferedReader(
                            new InputStreamReader(c.getInputStream(), "utf-8"))) {
                        String line;
                        while ((line = r.readLine()) != null) {
                            sb.append(line);
                        }
                    }
                    return sb.toString();
                }
            } catch (Exception ignored) {
                // the server is still binding; keep waiting
            } finally {
                if (c != null) {
                    c.disconnect();
                }
            }
            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                return null;
            }
        }
        return null;
    }

    /** The engine is up: show the studio it is serving from this device. */
    private void showStudio(final String python, final String health) {
        runOnUiThread(() -> {
            root.removeAllViews();
            TextView banner = new TextView(this);
            banner.setTextSize(11f);
            banner.setText("on-device engine: " + python + "\n" + health);
            root.addView(banner, new ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

            web = new WebView(this);
            WebSettings s = web.getSettings();
            s.setJavaScriptEnabled(true);
            s.setDomStorageEnabled(true);
            web.setBackgroundColor(0xFF050505);
            web.setWebViewClient(new WebViewClient());
            web.loadUrl("http://127.0.0.1:" + PORT + "/");
            root.addView(web, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        });
    }

    private void say(final String tag, final String text) {
        Log.i(TAG, tag + ": " + text);
        runOnUiThread(() -> {
            TextView v = new TextView(this);
            v.setTextSize(13f);
            v.setText(text);
            root.addView(v);
        });
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
