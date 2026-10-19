import os
import re
import time
import glob
import shutil
import zipfile
import subprocess
import urllib.parse
import requests
import yaml
from pathlib import Path

# --- Настройки ---
SECRET = os.environ.get("SECRET", "your_secret_path")
TG_TOKEN = os.environ.get("TG_TOKEN", "your_telegram_bot_token")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "your_ip:8080")
CONFIG = "/bot-config.yml"
QUEUE_DIR = "/queue"
DOWNLOADS = "/downloads"
AUDIO_EXTS = {'.mp3', '.m4a', '.flac', '.ogg', '.wav', '.aac', '.opus'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png'}
COVER_NAMES = ['cover', 'folder', 'front', 'album']
DESC_NAMES = ['description', 'info', 'readme']
MAX_DESC_LEN = 500

# Минимум свободного места (МБ). Если меньше — не конвертируем.
MIN_FREE_SPACE_MB = 3000

# Удалять оригиналы после успешной отправки ссылки?
DELETE_ORIGINALS = True


def get_recipients():
    with open(CONFIG, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    return [str(u['user_id']) for u in cfg.get('users', []) if u.get('notify') is True]


def send_telegram(text, parse_mode="HTML"):
    for chat_id in get_recipients():
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
                timeout=30,
            )
        except Exception as e:
            print(f"Telegram send failed to {chat_id}: {e}")


def notify_error(title, details=""):
    text = f"⚠️ Ошибка воркера\n\n{title}"
    if details:
        text += f"\n\n<code>{details[:800]}</code>"
    send_telegram(text)


def get_free_space_mb(path=DOWNLOADS):
    try:
        stat = shutil.disk_usage(path)
        return stat.free // (1024 * 1024)
    except Exception as e:
        print(f"disk_usage failed: {e}")
        return 999999


def is_audio_file(path):
    return Path(path).suffix.lower() in AUDIO_EXTS


def collect_audio_files(target):
    if os.path.isfile(target):
        return [target] if is_audio_file(target) else []
    files = []
    for root, dirs, names in os.walk(target):
        for n in names:
            if is_audio_file(n):
                files.append(os.path.join(root, n))
    files.sort()
    return files


def find_local_cover(folder):
    if not os.path.isdir(folder):
        return None
    for name in COVER_NAMES:
        for ext in ['.jpg', '.jpeg', '.png']:
            p = os.path.join(folder, name + ext)
            if os.path.isfile(p):
                return p
    try:
        for f in sorted(os.listdir(folder)):
            if Path(f).suffix.lower() in IMAGE_EXTS:
                return os.path.join(folder, f)
    except Exception:
        pass
    return None


def clean_for_search(name):
    """Чистит название от мусора, который мешает поиску в iTunes."""
    n = name
    n = re.sub(r'\[[^\]]*\]', ' ', n)         # [чит. ...]
    n = re.sub(r'\([^)]*\)', ' ', n)          # (Полина (ЛИ))
    n = re.sub(r'_\d+', ' ', n)               # _64
    n = re.sub(r'\b\d+\s*kbps\b', ' ', n, flags=re.IGNORECASE)
    n = re.sub(r'\bMP3\b', ' ', n, flags=re.IGNORECASE)
    n = re.sub(r'\bSHRDLU\b', ' ', n, flags=re.IGNORECASE)
    n = re.sub(r'\bWEB[- ]?DLRip\b', ' ', n, flags=re.IGNORECASE)
    n = re.sub(r'[,.!?;:«»""\'`~_\-–—]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def itunes_search(query, media='audiobook', entity='audiobook', limit=3):
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": media, "entity": entity,
                    "limit": limit, "country": "US"},
            timeout=15,
        )
        data = r.json()
        return data.get('results', [])
    except Exception as e:
        print(f"  iTunes request failed: {e}")
        return []


def find_online_cover(folder_name):
    """Возвращает (cover_url, description) или (None, None)."""
    clean = clean_for_search(folder_name)
    print(f"  Cleaned for search: '{clean}'")

    words = clean.split()
    queries = []
    if clean:
        queries.append(clean)
    if len(words) > 4:
        queries.append(' '.join(words[:4]))
    if len(words) > 2:
        queries.append(' '.join(words[:2]))

    seen = set()
    queries = [q for q in queries if q and not (q in seen or seen.add(q))]

    for q in queries:
        for media, entity in [('audiobook', 'audiobook'), ('music', 'album')]:
            results = itunes_search(q, media=media, entity=entity, limit=3)
            if results:
                q_words = set(w.lower() for w in q.split() if len(w) > 3)
                best = None
                best_score = 0
                for r in results:
                    title = (r.get('collectionName') or '').lower()
                    artist = (r.get('artistName') or '').lower()
                    score = sum(1 for w in q_words if w in title or w in artist)
                    if score > best_score:
                        best_score = score
                        best = r

                if best:
                    art = best.get('artworkUrl100') or best.get('artworkUrl60')
                    if art:
                        cover = art.replace('100x100bb', '1000x1000bb').replace('60x60bb', '1000x1000bb')
                        desc = best.get('description') or best.get('collectionName') or ''
                        print(f"  Found cover ({media}) for '{q}': {best.get('collectionName', '')[:60]}")
                        return cover, desc

    print(f"  No cover found after {len(queries)} queries")
    return None, None


def download_image(url, output_path):
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"  Image download failed: {e}")
        return False


def find_local_description(folder):
    if not os.path.isdir(folder):
        return None
    for name in DESC_NAMES:
        for ext in ['.txt', '.md']:
            p = os.path.join(folder, name + ext)
            if os.path.isfile(p):
                return p
    return None


def read_description(path):
    for enc in ['utf-8', 'cp1251', 'latin-1']:
        try:
            with open(path, encoding=enc) as f:
                text = f.read()
            text = text.strip()
            if len(text) > MAX_DESC_LEN:
                text = text[:MAX_DESC_LEN].rsplit(' ', 1)[0] + '…'
            return text
        except Exception:
            continue
    return None


def clean_description(text):
    if not text:
        return None
    d = text.replace('\r', ' ').replace('\n', ' ')
    d = re.sub(r'\s+', ' ', d).strip()
    if len(d) > MAX_DESC_LEN:
        d = d[:MAX_DESC_LEN].rsplit(' ', 1)[0] + '…'
    return d or None


def get_duration(file_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1',
             file_path],
            capture_output=True, text=True, timeout=60
        )
        return float(result.stdout.strip())
    except Exception as e:
        print(f"ffprobe failed on {file_path}: {e}")
        return 0.0


def build_chapters(audio_files, folder_name, description=None):
    chapters_path = "/tmp/chapters.txt"
    lines = [";FFMETADATA1", f"title={folder_name}", f"album={folder_name}"]
    if description:
        lines.append(f"description={description}")
    lines.append("")

    total_ms = 0
    for af in audio_files:
        dur = get_duration(af)
        if dur <= 0:
            continue
        dur_ms = int(dur * 1000)
        title = Path(af).stem
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={total_ms}",
            f"END={total_ms + dur_ms}",
            f"title={title}",
            "",
        ]
        total_ms += dur_ms

    with open(chapters_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return chapters_path, total_ms / 1000.0


def convert_to_m4b(target, output_path, is_folder):
    audio_files = collect_audio_files(target)
    if not audio_files:
        return False

    if len(audio_files) == 1 and audio_files[0].lower().endswith('.m4b'):
        shutil.copy(audio_files[0], output_path)
        return True

    list_path = "/tmp/concat_list.txt"
    with open(list_path, 'w', encoding='utf-8') as f:
        for af in audio_files:
            safe = af.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    folder_name = os.path.basename(target.rstrip('/')) if is_folder else Path(target).stem
    folder_dir = target if is_folder else os.path.dirname(target)

    # Обложка
    cover_path = find_local_cover(folder_dir) if is_folder else None
    online_description = None
    if cover_path:
        print(f"  Cover: local ({os.path.basename(cover_path)})")
    else:
        print(f"  Cover: searching online for '{folder_name}'...")
        url, online_description = find_online_cover(folder_name)
        if url:
            tmp_cover = "/tmp/cover_dl.jpg"
            if download_image(url, tmp_cover):
                cover_path = tmp_cover
                print(f"  Cover: downloaded from iTunes")

    # Описание: локальный файл → iTunes
    description = None
    if is_folder:
        desc_path = find_local_description(folder_dir)
        if desc_path:
            description = read_description(desc_path)
            if description:
                print(f"  Description: from {os.path.basename(desc_path)}")

    if not description and online_description:
        description = clean_description(online_description)
        if description:
            print(f"  Description: from iTunes ({len(description)} chars)")

    print(f"  Building chapters for {len(audio_files)} files...")
    chapters_path, total_dur = build_chapters(audio_files, folder_name, description)
    print(f"  Total duration: {total_dur/3600:.2f} hours")

    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
           '-f', 'concat', '-safe', '0', '-i', list_path,
           '-i', chapters_path]

    if cover_path:
        cmd += ['-i', cover_path]

    cmd += ['-map_metadata', '1', '-map_chapters', '1']
    if cover_path:
        cmd += ['-map', '0:a', '-map', '2:v', '-c:v', 'mjpeg',
                '-disposition:v:0', 'attached_pic']
    else:
        cmd += ['-map', '0:a']

    cmd += ['-c:a', 'aac', '-b:a', '64k', '-ac', '2',
            '-metadata', f'title={folder_name}',
            '-metadata', f'album={folder_name}']

    if description:
        cmd += ['-metadata', f'description={description}']

    cmd += ['-f', 'mp4', output_path]

    print("  Running ffmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg error:\n{result.stderr[-1500:]}")
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        return False
    return True


def create_zip(target, output_path):
    base_dir = os.path.dirname(target)
    base_name = os.path.basename(target)
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_STORED) as zf:
        if os.path.isfile(target):
            zf.write(target, base_name)
        else:
            for root, dirs, files in os.walk(target):
                for f in files:
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, base_dir)
                    zf.write(full, arc)


def delete_original(target, output_path):
    if not DELETE_ORIGINALS:
        return
    try:
        if os.path.abspath(target) == os.path.abspath(output_path):
            return
        if os.path.isdir(target):
            shutil.rmtree(target)
            print(f"  Deleted original folder: {target}")
        elif os.path.isfile(target):
            os.remove(target)
            print(f"  Deleted original file: {target}")
    except Exception as e:
        print(f"  Failed to delete original {target}: {e}")


def get_target_size(path):
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total
    except Exception:
        return 0


def format_size(num_bytes):
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} КБ"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} МБ"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} ГБ"


def get_sorted_tasks():
    task_files = glob.glob(os.path.join(QUEUE_DIR, "*.task"))
    result = []
    for tf in task_files:
        try:
            with open(tf, encoding='utf-8') as f:
                lines = f.read().split('\n')
            target = lines[1] if len(lines) >= 2 else ""
            size = get_target_size(target) if target else 0
        except Exception:
            size = 0
        result.append((size, tf))
    result.sort(key=lambda x: x[0])
    return result


def process_task(task_file):
    with open(task_file, encoding='utf-8') as f:
        lines = f.read().split('\n')
    if len(lines) < 3:
        print(f"Bad task: {task_file}")
        os.remove(task_file)
        return

    torrent_name, file_path, torrent_dir = lines[0], lines[1], lines[2]

    if file_path and os.path.exists(file_path) and file_path.rstrip('/') != DOWNLOADS:
        target = file_path
    elif torrent_dir and os.path.isdir(torrent_dir) and torrent_dir.rstrip('/') != DOWNLOADS:
        target = torrent_dir
    else:
        print(f"Bad task (empty or /downloads path): file_path={file_path!r}, torrent_dir={torrent_dir!r}")
        os.remove(task_file)
        return

    is_folder = os.path.isdir(target)
    audio_files = collect_audio_files(target)

    free_mb = get_free_space_mb()
    if free_mb < MIN_FREE_SPACE_MB:
        msg = f"Недостаточно места на диске для «{torrent_name}»"
        detail = f"Свободно: {free_mb} МБ, нужно минимум: {MIN_FREE_SPACE_MB} МБ"
        print(f"Skip: {detail}")
        notify_error(msg, detail)
        os.remove(task_file)
        return

    if audio_files:
        try:
            total_bytes = sum(os.path.getsize(f) for f in audio_files)
            need_mb = total_bytes // (1024 * 1024)
        except Exception:
            need_mb = 0
        if free_mb < need_mb + 500:
            msg = f"Недостаточно места для конвертации «{torrent_name}»"
            detail = f"Свободно: {free_mb} МБ, аудио: {need_mb} МБ"
            print(f"Skip: {detail}")
            notify_error(msg, detail)
            os.remove(task_file)
            return

        output = (target.rstrip('/') if is_folder else target) + ".m4b"
        print(f"→ m4b: {target}")
        ok = convert_to_m4b(target, output, is_folder)
        if not ok:
            print("M4B failed → fallback to ZIP")
            output = (target.rstrip('/') if is_folder else target) + ".zip"
            try:
                create_zip(target, output)
                file_type = "📦 Архив ZIP"
            except Exception as e:
                notify_error(
                    f"Не удалось обработать «{torrent_name}»",
                    f"M4B и ZIP оба упали: {e}"
                )
                os.remove(task_file)
                return
        else:
            file_type = "🎧 Аудиокнига M4B"
    elif is_folder:
        output = target.rstrip('/') + ".zip"
        print(f"→ zip: {target}")
        try:
            create_zip(target, output)
            file_type = "📦 Архив ZIP"
        except Exception as e:
            notify_error(f"ZIP не удался: {torrent_name}", str(e))
            os.remove(task_file)
            return
    else:
        output = target
        print(f"→ single file: {target}")
        file_type = "📄 Файл"

    if not os.path.exists(output):
        print(f"Output missing: {output}")
        notify_error(f"Результат не создан: {torrent_name}")
        os.remove(task_file)
        return

    size_mb = os.path.getsize(output) // (1024 * 1024)
    url_path = output.replace(DOWNLOADS + "/", "", 1)
    url_enc = urllib.parse.quote(url_path)
    url = f"http://{PUBLIC_HOST}/{SECRET}/{url_enc}"

    message = (
        f"✅ {torrent_name}\n"
        f"{file_type}, {size_mb} МБ\n\n"
        f"📥 <a href=\"{url}\">Скачать</a>"
    )
    send_telegram(message)
    print(f"Done: {torrent_name} ({file_type}, {size_mb} MB)")

    delete_original(target, output)

    os.remove(task_file)


def main():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    free_mb = get_free_space_mb()
    print(f"Worker started. Free space: {free_mb} МБ. Watching {QUEUE_DIR}")
    while True:
        try:
            for size, task_file in get_sorted_tasks():
                print(f"\n=== Processing {task_file} (размер: {format_size(size)}) ===")
                try:
                    process_task(task_file)
                except Exception as e:
                    print(f"Task error: {e}")
                    notify_error(f"Критическая ошибка задачи", str(e))
                    try:
                        os.remove(task_file)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
