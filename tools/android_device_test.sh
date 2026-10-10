#!/usr/bin/env bash
# Run from android/. The emulator action supplies ANDROID_SERIAL.
set -euo pipefail

adb shell cmd connectivity airplane-mode enable
adb shell svc wifi disable
adb shell svc data disable

is_offline() {
    test "$(adb shell settings get global airplane_mode_on | tr -d '\r')" = 1 &&
    adb shell cmd wifi status | tr -d '\r' | grep -Fx 'Wifi is disabled' >/dev/null &&
    adb shell dumpsys connectivity | grep -F 'Active default network: none' >/dev/null
}

# Connectivity changes are asynchronous. A stale global mobile_data value is
# not the state of the default subscription; require actual disconnection.
for attempt in $(seq 1 30); do
    if is_offline; then
        break
    fi
    sleep 1
done
is_offline

mkdir -p app/build/ci
record_offline_state() {
    {
        printf 'airplane_mode_on='
        adb shell settings get global airplane_mode_on
        printf 'wifi_on='
        adb shell settings get global wifi_on
        adb shell cmd wifi status | sed -n '1p'
        adb shell dumpsys connectivity | grep -F 'Active default network:'
    } | tee "app/build/ci/offline-$1.txt"
}
record_offline_state before

./gradlew --no-daemon --max-workers=2 --stacktrace :app:connectedValidationAndroidTest

# Neither the tests nor a late emulator callback may silently restore a network.
record_offline_state after
is_offline
