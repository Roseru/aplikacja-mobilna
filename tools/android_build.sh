#!/usr/bin/env bash
# Run from android/. Keep dependency/configuration failures before XML exists.
set -euo pipefail

mkdir -p app/build/ci
./gradlew --no-daemon --max-workers=2 --stacktrace \
    :app:assembleDebug :app:testDebugUnitTest :app:testValidationUnitTest :app:lintDebug \
    2>&1 | tee app/build/ci/gradle-build.log
