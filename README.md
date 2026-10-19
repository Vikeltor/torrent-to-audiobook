# 🎧 Telegram Torrent to Audiobook Bot

An automated pipeline that turns raw torrent downloads (MP3 folders) into perfectly formatted `.m4b` audiobooks with chapters and iTunes metadata, delivering them directly to your Telegram chat. 

It also handles regular files and non-audio torrents gracefully, packaging them into ZIP archives for easy download.

## ✨ Features
- **Telegram Integration:** Send a magnet link or `.torrent` file directly to the bot.
- **Smart Audio Processing:** Automatically detects audio folders, extracts chapter names, and gets duration via `ffprobe`.
- **iTunes API Integration:** Automatically fetches high-res cover art and book descriptions (with a fallback to local cover images).
- **FFmpeg Magic:** Stitches dozens of MP3s into a single AAC `.m4b` file with embedded chapter markers.
- **Universal File Support (ZIP fallback):** If a torrent contains non-audio files, documents, or mixed content, the bot automatically packs them into a `.zip` archive. Single files are delivered as-is.
- **Direct Delivery:** Bypasses Telegram's file size limits by hosting the output on a built-in Nginx server and sending a direct download link.
- **Smart Queue & Auto-cleanup:** Processes downloads from smallest to largest to provide quick results and automatically deletes original files after successful conversion to save disk space.
- **Resource Safeguards:** Includes built-in checks for free disk space, CPU limits, and memory boundaries to ensure the VPS stays stable.

## 🛠 Tech Stack
- **Python** (Worker logic, Telegram Bot API)
- **FFmpeg** (Audio processing and metadata embedding)
- **Docker & Docker Compose** (Containerization)
- **qBittorrent** (Torrent downloading)
- **Nginx** (Secure file hosting)

## 🚀 Quick Start
1. Clone the repository.
2. Copy the environment template and fill in your credentials:
   `cp .env.example .env`
3. Copy `bot-config.example.yml` to `bot-config.yml` and fill in your credentials.
3. Run `docker compose up -d --build`.
