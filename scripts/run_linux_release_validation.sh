#!/usr/bin/env bash
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: $0 OUTPUT_DIRECTORY APPIMAGETOOL APPIMAGE_RUNTIME_FILE" >&2
    exit 64
fi

output_directory=$1
appimagetool=$2
appimage_runtime=$3
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
log_path="$output_directory/build-and-test.log"
expected_appimagetool_sha256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
expected_appimage_runtime_x86_64_sha256=1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf
expected_appimage_runtime_aarch64_sha256=7d5d772b7c32f0c84caf0a452a3072a5709027d7eac5856feb89a7a7a8881372

mkdir -p "$output_directory" "$output_directory/partial"

finish() {
    status=$?
    if [ -d "$project_root/release" ]; then
        cp -a "$project_root/release/." "$output_directory/partial/" || true
    fi
    printf '%s\n' "$status" > "$output_directory/exit-code.txt"
    exit "$status"
}
trap finish EXIT HUP INT TERM

exec > >(tee "$log_path") 2>&1

cd "$project_root"
printf 'Onyx Linux 1.1.9 native release evidence\n'
printf 'UTC start: '
date -u +%FT%TZ
printf 'Kernel: '
uname -a
python --version
printf 'appimagetool SHA256: '
sha256sum "$appimagetool"
observed_appimagetool_sha256=$(sha256sum "$appimagetool" | awk '{print $1}')
if [ "$observed_appimagetool_sha256" != "$expected_appimagetool_sha256" ]; then
    echo "appimagetool SHA256 does not match the official 1.9.1 x86_64 pin" >&2
    exit 65
fi
case "$(uname -m)" in
    x86_64) expected_appimage_runtime_sha256=$expected_appimage_runtime_x86_64_sha256 ;;
    aarch64) expected_appimage_runtime_sha256=$expected_appimage_runtime_aarch64_sha256 ;;
    *) echo "unsupported AppImage runtime architecture: $(uname -m)" >&2; exit 65 ;;
esac
printf 'AppImage runtime SHA256: '
sha256sum "$appimage_runtime"
observed_appimage_runtime_sha256=$(sha256sum "$appimage_runtime" | awk '{print $1}')
if [ "$observed_appimage_runtime_sha256" != "$expected_appimage_runtime_sha256" ]; then
    echo "AppImage runtime SHA256 does not match the architecture pin" >&2
    exit 65
fi
printf 'source file count: '
find . -type f | wc -l

secret_tool=$(python -c 'from core.native_vault import _linux_secret_tool; print(_linux_secret_tool())')
printf 'trusted Secret Service helper: %s\n' "$secret_tool"

python -m pytest -q \
    tests/test_packaging_paths.py \
    tests/test_posix_artifact_root_authority_v1.py \
    tests/test_posix_kill_signal_v1.py \
    tests/test_posix_single_instance_v1.py \
    tests/test_posix_trusted_directory_v1.py \
    tests/test_release_version_v119.py \
    tests/test_documentation_precedence_v1.py

APPIMAGE_EXTRACT_AND_RUN=1 APPIMAGETOOL="$appimagetool" \
    APPIMAGE_RUNTIME_FILE="$appimage_runtime" \
    python scripts/build_release.py \
        --version 1.1.9 \
        --portable-current-negative-boundary-gate \
        --require-linux-secure-backend-probe

for artifact in \
    release/Onyx-1.1.9-Linux-x64.deb \
    release/Onyx-1.1.9-Linux-x64.tar.gz \
    release/Onyx-1.1.9-Linux-x64.AppImage \
    release/release-manifest-Linux-x64.json \
    release/SHA256SUMS-Linux-x64.txt \
    release/bundle-inventory-Linux-x64.json
do
    test -s "$artifact"
done
(cd release && sha256sum -c SHA256SUMS-Linux-x64.txt)

printf 'UTC finish: '
date -u +%FT%TZ
cp -a release/. "$output_directory/"
sha256sum release/* > "$output_directory/all-release-files.sha256"

trap - EXIT HUP INT TERM
printf '0\n' > "$output_directory/exit-code.txt"
