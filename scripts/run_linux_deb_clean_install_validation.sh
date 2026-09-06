#!/usr/bin/env bash
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 RELEASE_DEB" >&2
    exit 64
fi

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
requested=$1
case "$requested" in
    /*) artifact=$requested ;;
    *) artifact=$project_root/$requested ;;
esac

artifact=$(realpath "$artifact")
case "$artifact" in
    "$project_root"/*) ;;
    *)
        echo "DEB must be inside the project build context: $artifact" >&2
        exit 65
        ;;
esac
test -s "$artifact"

relative=${artifact#"$project_root"/}
case "$relative" in
    release/*.deb) ;;
    *)
        echo "DEB must be a release/*.deb artifact: $relative" >&2
        exit 66
        ;;
esac
tag=onyx-deb-clean-validation:$(sha256sum "$artifact" | cut -c1-16)

docker build --pull \
    --file "$project_root/packaging/linux/Dockerfile.deb-clean-validation" \
    --build-arg "ONYX_DEB=$relative" \
    --tag "$tag" \
    "$project_root"
docker run --rm "$tag"
