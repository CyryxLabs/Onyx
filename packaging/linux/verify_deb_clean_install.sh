#!/bin/sh
set -eu

package=onyx-ai-assistant
output_root=$HOME/native-startup-smoke
output=$output_root/onyx-native-startup-smoke-v1.json

test "$(dpkg-query -W -f='${Status}' "$package")" = "install ok installed"
depends=$(dpkg-query -W -f='${Depends}' "$package")
printf '%s\n' "$depends" | grep -Eq '(^|, )[[:space:]]*libegl1([[:space:]]*\([^)]*\))?([[:space:]]*,|$)'
test "$(dpkg-query -W -f='${Status}' libegl1)" = "install ok installed"
test -x /usr/bin/onyx
test -x /opt/cyryx-labs/onyx/Onyx

mkdir -p "$output_root"
chmod 0700 "$output_root"
rm -f "$output"
ONYX_NATIVE_STARTUP_SMOKE_OUTPUT="$output" \
    /usr/bin/onyx --native-startup-smoke-test

test -s "$output"
grep -Eq '"contract"[[:space:]]*:[[:space:]]*"OnyxNativeStartupSmoke.v1"' "$output"
grep -Eq '"status"[[:space:]]*:[[:space:]]*"passed"' "$output"
printf '%s\n' "Clean Debian DEB install and native startup smoke passed"
