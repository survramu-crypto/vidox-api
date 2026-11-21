import os
import shutil
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
        "direct_url": formats[-1]["url"] if formats else info.get("url"),
        "formats": formats,
    }

@app.get("/")
def home():
    cookie_path = get_cookie_file()
    return {
        "status": "online",
        "service": "VidoX API",
        "youtube_cookies_loaded": cookie_path is not None
    }

@app.get("/info")
def get_video_info(url: str = Query(..., description="Video URL")):
    cookie_path = get_cookie_file()
    errors = []
    attempts = []

    if cookie_path:
        attempts.append({
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "cookiefile": cookie_path,
        })

    attempts.append({
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    })

    for opts in attempts:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                result = parse_info(info)
                if result["formats"] or result["direct_url"]:
                    return result
        except Exception as e:
            errors.append(str(e))

    raise HTTPException(status_code=400, detail=" | ".join(errors) or "Could not fetch video")
