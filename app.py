import os
import shutil
import urllib.request
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

app = FastAPI(title="VidoX Backend Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def is_pot_server_alive():
    try:
        with urllib.request.urlopen("http://127.0.0.1:4416/ping", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_cookie_file():
    for path in ["/etc/secrets/cookies.txt", "cookies.txt"]:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            tmp_path = "/tmp/cookies.txt"
            shutil.copyfile(path, tmp_path)
            return tmp_path
    return None


def parse_info(info):
    formats = []
    for f in info.get("formats", []):
        if f.get("url") and f.get("vcodec") != "none" and f.get("acodec") != "none":
            formats.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "quality": f.get("format_note") or f"{f.get('height', '')}p",
                "url": f.get("url"),
            })
    if not formats:
        for f in info.get("formats", []):
            if f.get("url") and f.get("vcodec") != "none":
                formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "quality": f.get("format_note") or f"{f.get('height', '')}p",
                    "url": f.get("url"),
                })
    return {
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "direct_url": formats[0]["url"] if formats else info.get("url"),
        "formats": formats,
    }


@app.get("/")
def home():
    return {
        "status": "online",
        "service": "VidoX API",
        "pot_server_alive": is_pot_server_alive(),
    }


@app.get("/info")
def get_video_info(url: str = Query(..., description="Video URL")):
    errors = []
    is_youtube = "youtube.com" in url or "youtu.be" in url

    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
    }

    attempts = []

    if is_youtube:
        attempts.append({
            **base_opts,
            "extractor_args": {
                "youtube": {
                    "player_client": ["web", "mweb"],
                }
            },
        })
        attempts.append({**base_opts})
        attempts.append({
            **base_opts,
            "extractor_args": {
                "youtube": {
                    "player_client": ["mweb", "tv_embedded"],
                }
            },
        })
    else:
        attempts.append({**base_opts})
        cookie_path = get_cookie_file()
        if cookie_path:
            attempts.append({**base_opts, "cookiefile": cookie_path})

    for opts in attempts:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return parse_info(info)
        except Exception as e:
            errors.append(str(e))

    raise HTTPException(status_code=400, detail=" | ".join(errors))
