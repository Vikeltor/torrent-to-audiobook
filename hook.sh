#!/bin/bash
TORRENT_NAME="$1"
FILE_PATH="$2"
TORRENT_DIR="$3"
QUEUE_DIR="/queue"

mkdir -p "$QUEUE_DIR"
TASK_FILE="${QUEUE_DIR}/$(date +%s%N)-$$.task"
{
    echo "$TORRENT_NAME"
    echo "$FILE_PATH"
    echo "$TORRENT_DIR"
} > "$TASK_FILE"
echo "Queued: $TASK_FILE"
