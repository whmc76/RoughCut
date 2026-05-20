#!/bin/sh
set -eu

SRC="/mnt/docker-desktop-disk/data/docker/volumes/roughcut_minio_data/_data/roughcut/jobs"
DST="${ROUGHCUT_JOBS_MIGRATION_DST:-/mnt/host/e/WorkSpace/RoughCut/data/runtime/jobs}"
LIST="${ROUGHCUT_JOBS_MISSING_LIST:-/mnt/host/e/WorkSpace/RoughCut/data/runtime/jobs-missing.txt}"
LOG="${ROUGHCUT_JOBS_MIGRATION_LOG:-/mnt/host/e/WorkSpace/RoughCut/data/runtime/jobs-volume-migration.log}"
ERR="${ROUGHCUT_JOBS_MIGRATION_ERR:-/mnt/host/e/WorkSpace/RoughCut/data/runtime/jobs-volume-migration.err.log}"

mkdir -p "$DST"
touch "$LOG" "$ERR"

printf 'RESUME %s\n' "$(date -Iseconds)" >> "$LOG"

while IFS= read -r job; do
  job=$(printf '%s' "$job" | tr -d '\r')
  [ -n "$job" ] || continue
  if [ ! -d "$SRC/$job" ]; then
    printf 'MISSING_SOURCE %s\n' "$job" >> "$ERR"
    continue
  fi
  if [ -e "$DST/$job" ]; then
    printf 'SKIP %s\n' "$job" >> "$LOG"
    continue
  fi

  printf 'COPY %s\n' "$job" | tee -a "$LOG"
  cp -a "$SRC/$job" "$DST/$job" 2>>"$ERR"
done < "$LIST"

printf 'DONE %s\n' "$(date -Iseconds)" >> "$LOG"
