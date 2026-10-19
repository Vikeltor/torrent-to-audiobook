cd ~/torrent-cloud

for target in /mnt/torrents/*; do
    name=$(basename "$target")
    
    # Пропускаем готовые результаты
    case "$name" in
        *.m4b|*.zip) continue ;;
    esac
    
    # Пропускаем, если результат уже существует
    if [ -e "${target}.m4b" ] || [ -e "${target}.zip" ]; then
        echo "SKIP (результат есть): $name"
        continue
    fi
    
    # Пропускаем, если задача уже в очереди
    if grep -qr "/downloads/$name$" queue/ 2>/dev/null; then
        echo "SKIP (уже в очереди): $name"
        continue
    fi
    
    # Создаём задачу
    task_file="queue/$(date +%s%N)-$$.task"
    printf '%s\n/downloads/%s\n/downloads\n' "$name" "$name" > "$task_file"
    echo "Queued: $name"
    sleep 0.05
done

echo ""
echo "Всего задач в очереди: $(ls -1 queue/*.task 2>/dev/null | wc -l)"
