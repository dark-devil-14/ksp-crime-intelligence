#!/usr/bin/env sh
set -eu
IMAGE_NAME="${IMAGE_NAME:-ksp-crime-intelligence-v8:1.0.0}"
ARCHIVE_NAME="${ARCHIVE_NAME:-ksp-crime-intelligence-v8-amd64.tar}"
docker build --platform linux/amd64 -t "$IMAGE_NAME" .
docker save -o "$ARCHIVE_NAME" "$IMAGE_NAME"
echo "Created Docker archive: $ARCHIVE_NAME"
echo "In Catalyst CLI choose AppSail -> Docker Image -> Docker Archive and select this TAR file."
