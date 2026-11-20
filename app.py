import os
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

@app.get("/")
def home():
    return {"status": "online", "service": "VidoX API"}

@app.get("/info")
def get_video_info(url: str = Query(..., description="Video URL")):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get("formats", []):
                if f.get("url") and f.get("vcodec") != "none" and f.get("acodec") != "none":
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
                "direct_url": info.get("url") or (formats[-1]["url"] if formats else None),
                "formats": formats,
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
      
