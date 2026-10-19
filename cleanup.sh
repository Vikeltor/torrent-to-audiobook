#!/bin/bash
# Удаляем файлы и папки старше 5 дней в /mnt/torrents
find /mnt/torrents -mindepth 1 -mtime +5 -exec rm -rf {} + 2>/dev/null
echo "$(date '+%Y-%m-%d %H:%M:%S') - cleanup done" >> /var/log/torrent-cleanup.log
