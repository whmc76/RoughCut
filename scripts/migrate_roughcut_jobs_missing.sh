#!/bin/sh
set -eu

SRC="/mnt/docker-desktop-disk/data/docker/volumes/roughcut_minio_data/_data/roughcut/jobs"
DST="/mnt/host/f/roughcut_outputs/jobs"
LIST="/mnt/host/f/roughcut_outputs/jobs-missing.txt"
LOG="/mnt/host/f/roughcut_outputs/jobs-volume-migration.log"
ERR="/mnt/host/f/roughcut_outputs/jobs-volume-migration.err.log"

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
