"""
yt_downloader_cli.py - High-Fidelity YouTube Media Downloader (CLI Edition)
Location: ~/SE/projects/01_alias/00_yt/yt_downloader_cli.py

Features:
  1. Original Format MP4: Downloads highest available video & audio combined without lossy re-encoding.
  2. Zero-Quote Interactive Mode: Type "yt" and paste your link directly without escaping special characters.
  3. Direct CLI Mode: "yt <url>" downloads directly to ~/Music and exits cleanly.
"""

import sys
import os
import shutil
import argparse
from pathlib import Path
import yt_dlp


def get_default_music_dir() -> Path:
    """Returns the default download directory (~/SE/toolbox/downloads), creating it if necessary."""
    download_dir = Path(__file__).resolve().parent.parent.parent / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir


def get_node_runtime() -> dict:
    """Finds the available Node.js binary to handle YouTube n-sig / cipher execution."""
    candidates = [
        shutil.which("node"),
        shutil.which("nodejs"),
        str(Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "node"),
    ]
    for candidate in candidates:
        if candidate and (os.path.exists(candidate) or shutil.which(candidate)):
            return {"node": {"path": candidate}}
    return {}


def download_instagram_story_fallback(url: str, output_dir: Path, cookie_file: Path | None) -> int:
    """Fallback extractor for Instagram stories when yt-dlp's legacy reels_media endpoint fails."""
    import re
    from curl_cffi import requests
    import http.cookiejar

    if not cookie_file or not Path(cookie_file).is_file():
        return 0

    m = re.search(r'instagram\.com/stories/([^/?#]+)', url)
    if not m:
        return 0
    username = m.group(1)

    print(f"   \033[1;36m🔄 Using Direct Instagram Story Extractor for @{username}...\033[0m")
    cj = http.cookiejar.MozillaCookieJar(str(cookie_file))
    cj.load()
    s = requests.Session(impersonate="chrome120")
    for c in cj:
        s.cookies.set(c.name, c.value, domain=c.domain, path=c.path)

    headers = {
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "359341",
        "X-IG-WWW-Claim": "0",
        "Origin": "https://www.instagram.com",
        "Referer": "https://www.instagram.com/",
        "Accept": "*/*",
    }

    try:
        r = s.get("https://www.instagram.com/api/v1/feed/reels_tray/", headers=headers, timeout=15)
        if r.status_code != 200:
            return 0
        tray = r.json().get("tray", [])
        target_ids = []
        for item in tray:
            if item.get("user", {}).get("username") == username:
                target_ids = item.get("media_ids", [])
                break

        if not target_ids:
            return 0

        saved = 0
        for s_idx, mid in enumerate(target_ids, 1):
            mr = s.get(f"https://www.instagram.com/api/v1/media/{mid}/info/", headers=headers, timeout=15)
            if mr.status_code != 200:
                continue
            items = mr.json().get("items", [])
            for item in items:
                v_list = item.get("video_versions", [])
                img_list = item.get("image_versions2", {}).get("candidates", [])
                if v_list:
                    dl_url = v_list[0]["url"]
                    out_name = f"{username}_story_{s_idx}_{mid}.mp4"
                elif img_list:
                    dl_url = img_list[0]["url"]
                    out_name = f"{username}_story_{s_idx}_{mid}.jpg"
                else:
                    continue

                out_path = output_dir / out_name
                vr = s.get(dl_url, stream=True, timeout=30)
                with open(out_path, "wb") as f:
                    for chunk in vr.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                size_mb = out_path.stat().st_size / (1024 * 1024)
                print(f"   \033[1;32m✅ Successfully Downloaded Story {s_idx}/{len(target_ids)}:\033[0m {out_name} ({size_mb:.2f} MB)")
                print(f"      • Saved To: \033[1;33m{out_path}\033[0m\n")
                saved += 1
        return saved
    except Exception as ex:
        print(f"   ⚠️ Story fallback encountered error: {ex}")
        return 0


def download_media(
    urls: list[str],
    output_dir: Path = None,
    format_type: str = "mp3",
    cookies: str = None,
    browser: str = None,
) -> int:
    """Downloads YouTube and web media in MP3 (audio) or original high-quality MP4 (video) format."""
    if output_dir is None:
        output_dir = get_default_music_dir()
    else:
        output_dir = Path(output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

    is_mp3 = (format_type.lower() == "mp3")

    print("\n" + "=" * 65)
    if is_mp3:
        print("🎵  \033[1;36mYouTube High-Quality MP3 Downloader\033[0m")
        print(f"📁  Destination: \033[1;33m{output_dir}\033[0m")
        print(f"⚡  Format:      \033[1;32mHigh Quality MP3 (Best Audio Stream + VBR 0)\033[0m")
    else:
        print("🎬  \033[1;36mYouTube Original Format MP4 Downloader\033[0m")
        print(f"📁  Destination: \033[1;33m{output_dir}\033[0m")
        print(f"⚡  Format:      \033[1;32mOriginal Highest Quality MP4 (Native Streams)\033[0m")
    print("=" * 65 + "\n")

    if is_mp3:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "writethumbnail": False,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "quiet": False,
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                },
            ],
        }
    else:
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "writethumbnail": False,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "quiet": False,
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                }
            ],
        }

    js_runtime = get_node_runtime()
    if js_runtime:
        ydl_opts["js_runtimes"] = js_runtime

    if cookies:
        cookie_path = Path(cookies).expanduser().resolve()
        if cookie_path.exists():
            ydl_opts["cookiefile"] = str(cookie_path)
            print(f"🍪  Cookies:     \033[1;34mFile ({cookie_path})\033[0m")
        else:
            print(f"⚠️  \033[1;33mCookie file not found: {cookie_path}\033[0m")
    elif browser:
        ydl_opts["cookiesfrombrowser"] = (browser, None, None, None)
        print(f"🍪  Cookies:     \033[1;34mBrowser ({browser})\033[0m")
    else:
        candidates = [
            Path(__file__).resolve().parent.parent.parent / "cookies.txt",
            Path.home() / ".config" / "yt-dlp" / "cookies.txt",
            Path.home() / "cookies.txt",
        ]
        for c in candidates:
            if c.is_file():
                ydl_opts["cookiefile"] = str(c)
                print(f"🍪  Cookies:     \033[1;34mAuto-loaded ({c})\033[0m")
                break

    success_count = 0
    for idx, url in enumerate(urls, start=1):
        url = url.strip()
        if not url:
            continue
        print(f"\033[1;35m[{idx}/{len(urls)}]\033[0m Connecting: \033[4m{url}\033[0m")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "Unknown Title")
                acodec = info.get("acodec", "Native")
                
                if is_mp3:
                    out_file = output_dir / f"{title}.mp3"
                    print(f"\n\033[1;32m✅ Successfully Downloaded MP3:\033[0m {title}")
                    print(f"   • File:     \033[1;34m{title}.mp3\033[0m (Audio Stream: {acodec})")
                else:
                    ext = info.get("ext", "mp4")
                    vcodec = info.get("vcodec", "Native")
                    out_file = output_dir / f"{title}.{ext}"
                    print(f"\n\033[1;32m✅ Successfully Downloaded MP4:\033[0m {title}")
                    print(f"   • File:     \033[1;34m{title}.{ext}\033[0m (Video: {vcodec}, Audio: {acodec})")
                
                print(f"   • Saved To: \033[1;33m{out_file}\033[0m\n")
                success_count += 1
        except Exception as e:
            if "instagram.com/stories/" in url:
                cookie_file = ydl_opts.get("cookiefile")
                saved_stories = download_instagram_story_fallback(url, output_dir, cookie_file)
                if saved_stories > 0:
                    success_count += 1
                    continue

            print(f"\n\033[1;31m❌ Error downloading {url}:\033[0m {e}")
            if "403" in str(e) or "Forbidden" in str(e):
                print("   \033[1;33m💡 Tip: Run 'pip install -U yt-dlp' to update decipher keys.\033[0m\n")

    print("=" * 65)
    print(f"🎉  \033[1;32mFinished: {success_count}/{len(urls)} downloaded successfully.\033[0m")
    print("=" * 65 + "\n")
    return 0 if success_count == len(urls) else 1


def main():
    prog_name = Path(sys.argv[0]).stem
    default_format = "mp4" if "yt4" in prog_name else "mp3"

    parser = argparse.ArgumentParser(
        description=f"yt - High-Speed Pure YouTube Media Downloader (Invoked as {prog_name})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  yt https://youtu.be/xyz          (Download MP3 audio to ~/SE/toolbox/downloads)\n"
            "  yt4 https://youtu.be/xyz         (Download MP4 video to ~/SE/toolbox/downloads)\n"
            "  yt                               (Interactive prompt for MP3)\n"
            "  yt4                              (Interactive prompt for MP4)\n"
            "  yt <url> --format mp4            (Explicit format override)\n"
            "  yt <url> --dir ./custom_dir      (Custom destination directory)\n"
            "  yt4 <url> --browser firefox      (Use Firefox cookies for Instagram/auth)\n"
            "  yt4 <url> --cookies cookies.txt  (Use exported Netscape cookies file)"
        )
    )
    parser.add_argument("urls", nargs="*", help="YouTube video URLs to download")
    parser.add_argument("--dir", "-d", type=str, default=None, help="Custom download directory (default: ~/SE/toolbox/downloads)")
    parser.add_argument(
        "--format", "-f",
        choices=["mp3", "mp4"],
        default=default_format,
        help=f"Output format: mp3 (audio) or mp4 (video) (default: {default_format})"
    )
    parser.add_argument(
        "--mp3",
        action="store_const",
        dest="format",
        const="mp3",
        help="Download as high-quality MP3 audio"
    )
    parser.add_argument(
        "--mp4",
        action="store_const",
        dest="format",
        const="mp4",
        help="Download as original high-quality MP4 video"
    )
    parser.add_argument(
        "--cookies", "-c",
        type=str,
        default=None,
        help="Path to cookies.txt file for authentication (Instagram, age-restricted, etc.)"
    )
    parser.add_argument(
        "--browser", "-b",
        type=str,
        default=None,
        help="Browser name to extract cookies from (e.g., firefox, chrome, chromium, brave)"
    )

    args = parser.parse_args()

    if not args.urls:
        mode_label = "MP3 Audio" if args.format == "mp3" else "MP4 Video"
        icon_label = "🎵" if args.format == "mp3" else "🎬"
        print(f"\n\033[1;36m{icon_label} YouTube Downloader [{mode_label}] (Interactive Mode)\033[0m")
        print("💡 \033[90mTip: You can paste any link here without using quotes.\033[0m")
        try:
            raw_url = input("\n🔗 Paste YouTube URL: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\033[1;33mCancelled by user.\033[0m")
            sys.exit(0)

        if not raw_url:
            print("\033[1;31mNo URL provided. Exiting.\033[0m")
            sys.exit(1)
        args.urls = [raw_url]

    sys.exit(
        download_media(
            urls=args.urls,
            output_dir=args.dir,
            format_type=args.format,
            cookies=args.cookies,
            browser=args.browser,
        )
    )


if __name__ == "__main__":
    main()
