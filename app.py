import os
import random
import shutil
import time
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp

app = FastAPI(title="VidoX Advanced Backend Server", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory TTL cache (3 minutes) for ultra-fast repeat search & feed loads
CACHE_STORE = {}
CACHE_TTL_SECONDS = 180


def get_cached(key: str):
    item = CACHE_STORE.get(key)
    if not item:
        return None
    expires_at, data = item
    if time.time() > expires_at:
        CACHE_STORE.pop(key, None)
        return None
    return data


def set_cached(key: str, data):
    if len(CACHE_STORE) > 150:
        CACHE_STORE.clear()
    CACHE_STORE[key] = (time.time() + CACHE_TTL_SECONDS, data)


def is_pot_server_alive() -> bool:
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


def format_duration(seconds) -> str:
    if not seconds or not isinstance(seconds, (int, float)):
        return ""
    total = int(seconds)
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def parse_info(info: dict) -> dict:
    video_formats = []
    audio_formats = []
    seen_video_heights = set()

    raw_formats = info.get("formats") or []

    # 1. Combined video+audio formats first (best compatibility for direct download & in-app playback)
    for f in sorted(raw_formats, key=lambda x: x.get("height") or 0, reverse=True):
        url = f.get("url")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        height = f.get("height")
        if url and vcodec and vcodec != "none" and acodec and acodec != "none":
            label = f"{height}p" if height else (f.get("format_note") or "HD")
            if label not in seen_video_heights:
                seen_video_heights.add(label)
                video_formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext") or "mp4",
                    "quality": label,
                    "height": height or 0,
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "url": url,
                })

    # 2. Fallback to video-only streams if needed
    if not video_formats:
        for f in sorted(raw_formats, key=lambda x: x.get("height") or 0, reverse=True):
            url = f.get("url")
            vcodec = f.get("vcodec")
            height = f.get("height")
            if url and vcodec and vcodec != "none":
                label = f"{height}p" if height else (f.get("format_note") or "Video")
                if label not in seen_video_heights:
                    seen_video_heights.add(label)
                    video_formats.append({
                        "format_id": f.get("format_id"),
                        "ext": f.get("ext") or "mp4",
                        "quality": label,
                        "height": height or 0,
                        "filesize": f.get("filesize") or f.get("filesize_approx"),
                        "url": url,
                    })

    # 3. Audio-only streams (for MP3 / M4A / AAC options)
    for f in sorted(raw_formats, key=lambda x: x.get("abr") or 0, reverse=True):
        url = f.get("url")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        if url and (not vcodec or vcodec == "none") and acodec and acodec != "none":
            abr = int(f.get("abr") or 128)
            audio_formats.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext") or "m4a",
                "quality": f"{abr}kbps",
                "abr": abr,
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "url": url,
            })

    best_direct_url = (
        video_formats[0]["url"]
        if video_formats
        else (audio_formats[0]["url"] if audio_formats else info.get("url"))
    )

    return {
        "id": info.get("id"),
        "title": info.get("title") or "VidoX_Media",
        "thumbnail": info.get("thumbnail"),
        "channel": info.get("uploader") or info.get("channel") or "YouTube",
        "duration": info.get("duration"),
        "duration_text": format_duration(info.get("duration")),
        "direct_url": best_direct_url,
        "formats": video_formats,
        "audio_formats": audio_formats[:5],
    }


def run_yt_search(query: str, count: int = 15, latest: bool = False) -> list:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
    }

    if latest:
        encoded_q = urllib.parse.quote_plus(query)
        target = f"https://www.youtube.com/results?search_query={encoded_q}&sp=CAI%253D"
        ydl_opts["playlistend"] = count
    else:
        target = f"ytsearch{count}:{query}"

    results = []
    seen_ids = set()

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target, download=False)
        entries = info.get("entries") or []
        for entry in entries:
            if not entry:
                continue
            vid_id = entry.get("id")
            if not vid_id or len(vid_id) != 11 or vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)
            dur = entry.get("duration")
            results.append({
                "id": vid_id,
                "title": entry.get("title") or "Untitled Video",
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "thumbnail": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                "duration": dur,
                "duration_text": format_duration(dur),
                "channel": entry.get("uploader") or entry.get("channel") or "YouTube",
                "view_count": entry.get("view_count"),
            })
            if len(results) >= count:
                break

    return results


@app.get("/")
def home():
    return {
        "status": "online",
        "service": "VidoX API",
        "version": "2.0.0",
        "pot_server_alive": is_pot_server_alive(),
        "endpoints": ["/", "/search", "/feed", "/info", "/stream"],
    }


@app.get("/search")
def search_videos(
    q: str = Query(..., min_length=1, description="Search keyword"),
    page: int = Query(1, ge=1, le=10),
    limit: int = Query(12, ge=1, le=25),
    latest: bool = Query(False, description="Sort by newest upload date"),
):
    clean_q = q.strip()
    cache_key = f"search:{clean_q.lower()}:p{page}:l{limit}:new{latest}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    fetch_count = min(page * limit, 40)
    try:
        all_items = run_yt_search(clean_q, count=fetch_count, latest=latest)
        start_idx = (page - 1) * limit
        paged_items = all_items[start_idx : start_idx + limit]
        if not paged_items and page == 1 and latest:
            # Fallback to standard search if upload-date filter returns empty
            all_items = run_yt_search(clean_q, count=limit, latest=False)
            paged_items = all_items[:limit]

        payload = {
            "query": clean_q,
            "page": page,
            "latest": latest,
            "count": len(paged_items),
            "has_more": len(all_items) >= fetch_count,
            "results": paged_items,
        }
        set_cached(cache_key, payload)
        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Search failed: {str(e)}")


FEED_QUERIES = {
    "all": [
        "trending videos india 2026",
        "latest bollywood songs 2026",
        "motu patlu new episodes",
        "viral comedy videos india",
        "new hindi movie trailers 2026",
        "trending shorts india 2026",
    ],
    "trending": [
        "trending videos india today",
        "viral videos india 2026",
        "top trending youtube india",
    ],
    "music": [
        "latest hindi songs 2026",
        "new bollywood hit songs 2026",
        "punjabi hit songs 2026",
    ],
    "movies": [
        "new hindi movie trailer 2026",
        "south indian hindi dubbed full movie",
        "bollywood action scenes hd",
    ],
    "cartoons": [
        "motu patlu new episode",
        "shinchan hindi episodes",
        "doraemon hindi new episode",
    ],
    "tech": [
        "best smartphones india 2026",
        "tech unboxing hindi",
        "android tips and tricks hindi",
    ],
}


@app.get("/feed")
def get_home_feed(
    category: str = Query("all", description="Feed category"),
    page: int = Query(1, ge=1, le=15),
    refresh: int = Query(0, description="Increment on pull-to-refresh for fresh videos"),
):
    cat_key = category.strip().lower()
    queries = FEED_QUERIES.get(cat_key, FEED_QUERIES["all"])
    idx = (page - 1 + refresh) % len(queries)
    selected_query = queries[idx]

    cache_key = f"feed:{cat_key}:p{page}:r{refresh}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    try:
        items = run_yt_search(selected_query, count=12, latest=False)
        if refresh > 0:
            random.shuffle(items)
        payload = {
            "category": cat_key,
            "page": page,
            "refresh": refresh,
            "query_used": selected_query,
            "count": len(items),
            "has_more": True,
            "results": items,
        }
        set_cached(cache_key, payload)
        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Feed failed: {str(e)}")


@app.get("/info")
def get_video_info(url: str = Query(..., description="Video URL")):
    clean_url = url.strip()
    cache_key = f"info:{clean_url}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    errors = []
    is_youtube = "youtube.com" in clean_url or "youtu.be" in clean_url
    cookie_path = get_cookie_file()

    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
    }

    attempts = []

    if is_youtube:
        if cookie_path:
            attempts.append({
                **base_opts,
                "cookiefile": cookie_path,
                "extractor_args": {"youtube": {"player_client": ["web", "mweb"]}},
            })
        attempts.append({
            **base_opts,
            "extractor_args": {"youtube": {"player_client": ["web", "mweb"]}},
        })
        attempts.append({**base_opts})
        attempts.append({
            **base_opts,
            "extractor_args": {"youtube": {"player_client": ["mweb", "tv_embedded"]}},
        })
    else:
        attempts.append({**base_opts})
        if cookie_path:
            attempts.append({**base_opts, "cookiefile": cookie_path})

    for opts in attempts:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
                parsed = parse_info(info)
                set_cached(cache_key, parsed)
                return parsed
        except Exception as e:
            errors.append(str(e))

    raise HTTPException(status_code=400, detail=" | ".join(errors))


@app.get("/stream")
def proxy_media_stream(
    media_url: str = Query(..., description="Direct media stream URL"),
    filename: str = Query("VidoX_Download.mp4", description="Download file name"),
):
    try:
        req = urllib.request.Request(
            media_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
                )
            },
        )
        remote = urllib.request.urlopen(req, timeout=20)
        content_type = remote.headers.get("Content-Type", "application/octet-stream")
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ") or "VidoX_Download.mp4"

        def iterfile():
            try:
                while True:
                    chunk = remote.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                remote.close()

        return StreamingResponse(
            iterfile(),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Stream failed: {str(e)}")
