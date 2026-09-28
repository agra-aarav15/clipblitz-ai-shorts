package com.clipblitz.studio;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * ClipBlitz Studio companion app: a thin, honest WebView shell. All rendering happens on
 * the machine that runs the studio (a PC, a laptop, or Termux); this app only controls and
 * previews. First launch shows the app mark and asks for the studio's address (printed by the
 * studio on startup, and shown in its Connect screen under "Phone and network"), remembers it,
 * and from then on opens straight into the studio.
 */
public class MainActivity extends Activity {

    private WebView web;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("clipblitz_studio", Context.MODE_PRIVATE);
        String saved = prefs.getString("url", "");
        if (saved == null || saved.length() == 0) {
            showAddressScreen();
        } else {
            openStudio(saved);
        }
    }

    private void showAddressScreen() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#050505"));
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(28), dp(28), dp(28), dp(28));

        // The app photo, drawn from the same brand asset as the launcher icon.
        ImageView mark = new ImageView(this);
        mark.setImageResource(R.mipmap.ic_launcher);
        mark.setContentDescription("ClipBlitz Studio");
        LinearLayout.LayoutParams markParams =
                new LinearLayout.LayoutParams(dp(96), dp(96));
        markParams.gravity = Gravity.CENTER_HORIZONTAL;
        markParams.bottomMargin = dp(14);
        root.addView(mark, markParams);

        TextView title = new TextView(this);
        title.setText("ClipBlitz Studio");
        title.setTextColor(Color.WHITE);
        title.setTextSize(26);
        title.setGravity(Gravity.CENTER);

        TextView hint = new TextView(this);
        hint.setText("Start the studio on your computer, then enter the address it prints "
                + "(looks like http://192.168.x.x:4300). Both devices must be on the same Wi-Fi. "
                + "Your computer renders the clips; this app controls and previews.");
        hint.setTextColor(Color.parseColor("#999999"));
        hint.setTextSize(14);
        hint.setPadding(0, dp(14), 0, dp(22));

        final EditText input = new EditText(this);
        input.setHint("http://192.168.x.x:4300");
        input.setInputType(EditorInfo.TYPE_TEXT_VARIATION_URI);
        input.setTextColor(Color.WHITE);
        input.setSingleLine(true);

        Button go = new Button(this);
        go.setText("Connect to my studio");
        go.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                String url = input.getText().toString().trim();
                if (url.length() == 0) {
                    input.setError("Enter the address the studio printed");
                    return;
                }
                if (!url.startsWith("http://") && !url.startsWith("https://")) {
                    url = "http://" + url;
                }
                prefs.edit().putString("url", url).apply();
                openStudio(url);
            }
        });

        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        root.addView(title, tp);
        root.addView(hint, tp);
        root.addView(input, tp);
        root.addView(go, tp);

        TextView footer = new TextView(this);
        footer.setText("ClipBlitz Studio " + versionName());
        footer.setTextColor(Color.parseColor("#666666"));
        footer.setTextSize(12);
        footer.setGravity(Gravity.CENTER);
        footer.setPadding(0, dp(18), 0, 0);
        root.addView(footer, tp);
        setContentView(root);
    }

    /** The version the APK was actually built with, not a string we can forget to bump. */
    private String versionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "";
        }
    }

    private void openStudio(String url) {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        web.setBackgroundColor(Color.parseColor("#050505"));   // no white flash before the page paints
        web.setWebViewClient(new WebViewClient());
        web.loadUrl(url);
        setContentView(web);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else if (web != null) {
            web = null;
            prefs.edit().putString("url", "").apply();
            showAddressScreen();
        } else {
            super.onBackPressed();
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
