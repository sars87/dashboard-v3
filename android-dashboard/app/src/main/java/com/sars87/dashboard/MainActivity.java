package com.sars87.dashboard;

import android.annotation.SuppressLint;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class MainActivity extends android.app.Activity {
    private static final String DASHBOARD_URL = "http://192.168.100.3:8088";
    private static final String TAILSCALE_PACKAGE = "com.tailscale.ipn";
    private static final int CHECK_INTERVAL_SECONDS = 3;

    private WebView webView;
    private SwipeRefreshLayout swipeRefreshLayout;
    private LinearLayout recoveryView;
    private ProgressBar progress;
    private TextView status;
    private ScheduledExecutorService checker;
    private boolean dashboardLoaded = false;

    @Override
    @SuppressLint("SetJavaScriptEnabled")
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createInterface();

        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                if (swipeRefreshLayout != null) {
                    swipeRefreshLayout.setRefreshing(false);
                }
            }
        });

        // Enable cookies for session persistence across restarts
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(webView, true);

        startCheckingDashboard();
    }

    private void createInterface() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.rgb(6, 10, 19));

        progress = new ProgressBar(this);
        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setTextSize(18);
        status.setGravity(Gravity.CENTER);
        status.setPadding(36, 24, 36, 32);

        Button tailscaleButton = new Button(this);
        tailscaleButton.setText("Open Tailscale");
        tailscaleButton.setAllCaps(false);
        tailscaleButton.setOnClickListener(v -> openTailscale());

        recoveryView = new LinearLayout(this);
        recoveryView.setOrientation(LinearLayout.VERTICAL);
        recoveryView.setGravity(Gravity.CENTER);
        recoveryView.setPadding(36, 36, 36, 36);
        recoveryView.addView(progress);
        recoveryView.addView(status);
        recoveryView.addView(tailscaleButton);

        webView = new WebView(this);
        webView.setVisibility(View.GONE);

        swipeRefreshLayout = new SwipeRefreshLayout(this);
        swipeRefreshLayout.addView(webView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.MATCH_PARENT));
        swipeRefreshLayout.setOnRefreshListener(() -> {
            if (dashboardLoaded) {
                webView.reload();
            } else {
                swipeRefreshLayout.setRefreshing(false);
            }
        });
        swipeRefreshLayout.setVisibility(View.GONE);

        root.addView(recoveryView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.MATCH_PARENT));
        root.addView(swipeRefreshLayout, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.MATCH_PARENT));

        setContentView(root);
    }

    private void startCheckingDashboard() {
        dashboardLoaded = false;
        recoveryView.setVisibility(View.VISIBLE);
        swipeRefreshLayout.setVisibility(View.GONE);
        status.setText("Checking dashboard…");
        if (checker != null) checker.shutdownNow();
        checker = Executors.newSingleThreadScheduledExecutor();
        checker.scheduleWithFixedDelay(this::checkDashboard, 0, CHECK_INTERVAL_SECONDS, TimeUnit.SECONDS);
    }

    private void checkDashboard() {
        boolean reachable = false;
        try {
            HttpURLConnection connection = (HttpURLConnection) new URL(DASHBOARD_URL).openConnection();
            connection.setConnectTimeout(2500);
            connection.setReadTimeout(2500);
            connection.setRequestMethod("GET");
            int code = connection.getResponseCode();
            reachable = code >= 200 && code < 400;
            connection.disconnect();
        } catch (Exception ignored) {
        }
        boolean online = reachable;
        runOnUiThread(() -> {
            if (online && !dashboardLoaded) showDashboard();
            else if (!online && !dashboardLoaded) {
                status.setText("Dashboard unavailable. Connect Tailscale, then this app will continue automatically.");
            }
        });
    }

    private void showDashboard() {
        dashboardLoaded = true;
        if (checker != null) checker.shutdownNow();
        recoveryView.setVisibility(View.GONE);
        swipeRefreshLayout.setVisibility(View.VISIBLE);
        webView.loadUrl(DASHBOARD_URL + "/");
    }

    private void openTailscale() {
        Intent intent = getPackageManager().getLaunchIntentForPackage(TAILSCALE_PACKAGE);
        if (intent == null) {
            Toast.makeText(this, "Install Tailscale and sign in first.", Toast.LENGTH_LONG).show();
            return;
        }
        startActivity(intent);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!dashboardLoaded) startCheckingDashboard();
    }

    @Override
    protected void onDestroy() {
        if (checker != null) checker.shutdownNow();
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}
