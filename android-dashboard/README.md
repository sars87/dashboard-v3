# Home Dashboard Android app

This Android app opens the Pi-hole dashboard at `http://192.168.100.3:8088`.

## Behaviour

1. Probes the dashboard every three seconds.
2. Opens the dashboard's existing login page in a mobile WebView when it is reachable.
3. When unreachable, shows an **Open Tailscale** button and retries automatically after Tailscale connects.

Android does not allow this app to silently activate Tailscale. Install Tailscale, sign in, and approve its VPN permission before using the recovery button.

## Build the APK

1. Open the `android-dashboard` folder in Android Studio.
2. Let Android Studio install the requested Android SDK / Gradle components.
3. Choose **Build → Build APK(s)**.
4. The debug APK is created at `app/build/outputs/apk/debug/app-debug.apk`.
