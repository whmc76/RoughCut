#!/bin/sh
set -eu

SRC="/mnt/docker-desktop-disk/data/docker/volumes/roughcut_minio_data/_data/roughcut/jobs"
DST="/mnt/host/f/roughcut_outputs/jobs"

mkdir -p "$DST"
echo "START $(date -Iseconds)"

for dir in "$SRC"/*; do
  [ -d "$dir" ] || continue
  name=$(basename "$dir")
  if [ -d "$DST/$name" ]; then
    continue
  fi
  cp -a "$dir" "$DST/$name"
  echo "COPIED $name"
done

echo "DONE $(date -Iseconds)"
