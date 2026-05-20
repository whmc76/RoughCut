#!/bin/sh
set -eu

SRC="/mnt/docker-desktop-disk/data/docker/volumes/roughcut_minio_data/_data/roughcut/jobs"
DST="${ROUGHCUT_JOBS_MIGRATION_DST:-/mnt/host/e/WorkSpace/RoughCut/data/runtime/jobs}"

mkdir -p "$DST"
echo "START $(date -Iseconds)"
cp -au "$SRC"/. "$DST"/
echo "DONE $(date -Iseconds)"
