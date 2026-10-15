#!/usr/bin/env bash
# Run from android/. The emulator action supplies ANDROID_SERIAL.
set -euo pipefail

mkdir -p app/build/ci
record_framework_state() {
    {
        adb shell getprop sys.boot_completed
        for service in phone connectivity wifi settings package; do
            adb shell service check "$service"
        done
    } >app/build/ci/startup-services.txt 2>&1 || true
}
device_stage=framework_ready
trap 'device_test_status=$?; printf "stage=%s\nexit_code=%s\n" "$device_stage" "$device_test_status" >app/build/ci/setup-status.txt; if (( device_test_status != 0 )); then record_framework_state; cat app/build/ci/setup-status.txt >&2; fi; exit "$device_test_status"' EXIT

# sys.boot_completed may be set before telephony/ConnectivityService register.
# Wait before changing airplane mode; do not retry or skip application tests.
framework_ready() {
    test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1 || return 1
    for service in phone connectivity wifi settings package; do
        adb shell service check "$service" | tr -d '\r' |
            grep -Fx "Service $service: found" >/dev/null || return 1
    done
}
for attempt in $(seq 1 60); do
    if framework_ready; then
        break
    fi
    sleep 2
done
if ! framework_ready; then
    echo 'Android framework services unavailable after bounded startup wait' >&2
    exit 20
fi
record_framework_state

# Configure only the ephemeral test device. Android 15 otherwise permits Wi-Fi
# overrides in airplane mode; a delayed system callback can restore a network.
# Establish the policy before toggling airplane mode, including saved APM state.
configure_offline() {
    device_stage=airplane_disable
    adb shell cmd connectivity airplane-mode disable || return 1
    device_stage=radio_policy
    adb shell settings put global airplane_mode_radios cell,bluetooth,wifi,nfc,wimax || return 1
    device_stage=toggle_policy
    adb shell settings put global airplane_mode_toggleable_radios bluetooth || return 1
    device_stage=wifi_apm_policy
    adb shell settings put secure wifi_apm_state 0 || return 1
    device_stage=wifi_disable
    adb shell svc wifi disable || return 1
    device_stage=airplane_enable
    adb shell cmd connectivity airplane-mode enable || return 1
    device_stage=data_disable
    adb shell svc data disable || return 1
    device_stage=offline_verification
    is_offline
}

is_offline() {
    test "$(adb shell settings get global airplane_mode_on | tr -d '\r')" = 1 &&
    adb shell cmd wifi status | tr -d '\r' | grep -Fx 'Wifi is disabled' >/dev/null &&
    adb shell dumpsys connectivity | grep -F 'Active default network: none' >/dev/null
}

# Connectivity changes are asynchronous. A stale global mobile_data value is
# not the state of the default subscription; require actual disconnection.
offline_configured=0
for attempt in $(seq 1 30); do
    if configure_offline; then
        offline_configured=1
        break
    fi
    printf 'attempt=%s stage=%s result=not_ready\n' "$attempt" "$device_stage" >>app/build/ci/setup-attempts.txt
    sleep 1
done
if (( offline_configured == 0 )); then
    echo 'Android offline setup unavailable after bounded startup wait' >&2
    exit 21
fi
is_offline

mkdir -p app/build/ci
record_offline_state() {
    {
        printf 'airplane_mode_on='
        adb shell settings get global airplane_mode_on
        printf 'airplane_mode_toggleable_radios='
        adb shell settings get global airplane_mode_toggleable_radios
        printf 'wifi_apm_state='
        adb shell settings get secure wifi_apm_state
        printf 'wifi_on='
        adb shell settings get global wifi_on
        adb shell cmd wifi status | sed -n '1p'
        adb shell dumpsys connectivity | grep -F 'Active default network:'
    } | tee "app/build/ci/offline-$1.txt"
}
record_offline_state before

device_stage=application_tests
./gradlew --no-daemon --max-workers=2 --stacktrace :app:connectedValidationAndroidTest \
    2>&1 | tee app/build/ci/gradle-device.log

# Neither the tests nor a late emulator callback may silently restore a network.
device_stage=offline_after_tests
record_offline_state after
is_offline
device_stage=complete
