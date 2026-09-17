# HireBuddha Dialer (Android)

Rep-facing app for mobile campaigns: the rep's phone calls the tenant's AI-agent number and the lead, merges them, and the AI talks to the lead. Design: [`docs/mobile-dialer-app`](../../docs/mobile-dialer-app/README.md). Deployment steps: [doc 10](../../docs/mobile-dialer-app/10-implementation-and-deployment.md).

## Stack

Kotlin 2.4 · Jetpack Compose (Material 3) · Hilt · Retrofit 3 + kotlinx.serialization · OkHttp WebSocket · Room + WorkManager (event outbox) · Android Telecom `InCallService` (default phone app). minSdk 29, compileSdk 37, targetSdk 36. AGP 9.4, Gradle 9.7.1, JDK 21.

## Build

```bash
echo "sdk.dir=/path/to/Android/Sdk" > local.properties
./gradlew :app:assembleDebug          # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:testDebugUnitTest      # orchestrator tests (fake telecom/backend/push, virtual time)
./gradlew :app:lintDebug
./gradlew :app:assembleRelease        # signed when keystore.properties exists (see doc 10 §3 step 6)
```

The debug build installs as `com.hirebuddha.dialer.debug` alongside a release install. The server defaults to `https://gateway.hirebuddha.com/`; you can change it on the login screen under **Server settings**.

## Layout

```
app/src/main/java/com/hirebuddha/dialer/
  data/api        Retrofit API, DTOs, auth + token refresh, server URL rewrite
  data/auth       Keystore-encrypted session, login/me
  data/outbox     Room event outbox + WorkManager flush
  data/push       /mobile/ws push socket
  data/repo       devices, campaigns, analytics
  telecom         InCallService, CallRegistry (CallControl), SIM selection, dial pad + incoming-call UI
  run             CallOrchestrator (AI-first flow), RunController, RunService (foreground, phoneCall)
  ui              Compose screens: login, onboarding, campaigns, create, run, call detail, analytics, settings
```

## Notes

- The app must hold the **default phone app** role to detect answers, hold/merge calls, send DTMF and mute the rep. Onboarding requests it.
- The rep is **muted automatically** when the lead is merged in and can tap **Unmute** to speak or **Take over** to drop the AI.
- FCM is not wired on the device yet (needs a Firebase project). Pushes arrive over the WebSocket while a run is active, and the orchestrator falls back to polling the attempt status.
