#youtube_video.py
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False

from config import is_windows, is_mac, is_linux
from core.paths import config_file, resource_root


def _get_base_dir() -> Path:
    return resource_root()


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = config_file()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"
_MAX_VIDEO_RESULTS = 10


def _get_api_key() -> str:
    from core.credentials import get
    return get(required=True) or ""


def _open_url(url: str) -> None:
    try:
        if is_mac():
            subprocess.Popen(["open", url])
        elif is_linux():
            subprocess.Popen(["xdg-open", url])
        else:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
    except Exception as e:
        print(f"[YouTube] ⚠️ open_url failed: {e}")

def _scrape_first_video_url(query: str) -> str | None:

    if not _REQUESTS_OK:
        return None

    search_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}"
        f"&sp={_YT_VIDEO_FILTER}"
    )

    try:
        r    = requests.get(search_url, headers=HEADERS, timeout=10)
        html = r.text

        video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)

        seen = set()
        for vid in video_ids:
            if vid in seen:
                continue
            seen.add(vid)

            if f'/shorts/{vid}' in html:
                continue
            return f"https://www.youtube.com/watch?v={vid}"

    except Exception as e:
        print(f"[YouTube] ⚠️ scrape_first_video_url failed: {e}")

    return None


def _bounded_result_count(value: object, *, default: int = 8) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = default
    return max(1, min(requested, _MAX_VIDEO_RESULTS))


def _initial_data(html: str) -> dict | None:
    """Decode YouTube's initial data object without treating chrome as videos."""
    decoder = json.JSONDecoder()
    for marker in ("var ytInitialData =", "window[\"ytInitialData\"] ="):
        start = html.find(marker)
        if start < 0:
            continue
        payload = html[start + len(marker) :].lstrip()
        try:
            decoded, _ = decoder.raw_decode(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(decoded, dict):
            return decoded
    return None


def _text_value(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    simple = value.get("simpleText")
    if isinstance(simple, str):
        return simple.strip()
    runs = value.get("runs")
    if not isinstance(runs, list):
        return ""
    return "".join(
        run.get("text", "")
        for run in runs
        if isinstance(run, dict) and isinstance(run.get("text"), str)
    ).strip()


def _video_results(html: str, max_results: int) -> list[dict]:
    data = _initial_data(html)
    if data is None:
        return []
    limit = _bounded_result_count(max_results)
    results: list[dict] = []
    seen: set[str] = set()

    def visit(value: object) -> None:
        if len(results) >= limit:
            return
        if isinstance(value, dict):
            renderer = value.get("videoRenderer")
            if isinstance(renderer, dict):
                video_id = renderer.get("videoId")
                title = _text_value(renderer.get("title"))
                if (
                    isinstance(video_id, str)
                    and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
                    and title
                    and video_id not in seen
                ):
                    seen.add(video_id)
                    results.append(
                        {
                            "rank": len(results) + 1,
                            "video_id": video_id,
                            "title": title,
                            "channel": _text_value(renderer.get("ownerText")) or "Unknown",
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                        }
                    )
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return results


def _scrape_search_results(query: str, max_results: int = 5) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    url = (
        "https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    )
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return _video_results(response.text, max_results)
    except Exception as exc:
        print(f"[YouTube] ⚠️ Search scrape failed: {exc}")
        return []

def _extract_video_id(url: str) -> str | None:
    match = re.search(
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})", url
    )
    return match.group(1) if match else None


def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def _ask_for_url(prompt_text: str = "YouTube video URL:") -> str | None:
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()

        url = simpledialog.askstring("Onyx", prompt_text, parent=root)
        return url.strip() if url else None
    except Exception as e:
        print(f"[YouTube] ⚠️ URL dialog failed: {e}")
        return None


def _get_transcript(video_id: str) -> str | None:
    if not _TRANSCRIPT_OK:
        return None
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "list"):
            transcript_list = api.list(video_id)
        else:  # compatibility with youtube-transcript-api < 1.2
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript      = None

        lang_priority = ["en", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"]

        try:
            transcript = transcript_list.find_manually_created_transcript(lang_priority)
        except Exception:
            pass

        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(lang_priority)
            except Exception:
                for t in transcript_list:
                    transcript = t
                    break

        if transcript is None:
            return None

        fetched = transcript.fetch()
        return " ".join(
            entry.text if hasattr(entry, "text") else entry["text"]
            for entry in fetched
        )

    except Exception as e:
        print(f"[YouTube] ⚠️ Transcript fetch failed: {e}")
        return None


def _summarize_with_gemini(transcript: str, video_url: str) -> str:
    from google import genai as _genai
    from google.genai import types

    _client = _genai.Client(api_key=_get_api_key())
    max_chars = 80000
    truncated = transcript[:max_chars] + ("..." if len(transcript) > max_chars else "")
    response  = _client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Please summarize this YouTube video transcript:\n\n{truncated}",
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are Onyx, a Cyryx Labs AI assistant using a configured cloud model. "
                "Summarize YouTube video transcripts clearly and concisely. "
                "Structure: 1-sentence overview, then 3-5 key points. "
                "Be direct. Address the user as 'sir'. "
                "Match the language of the transcript."
            )
        )
    )
    return response.text.strip()


def _save_summary(content: str, video_url: str) -> str:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"youtube_summary_{ts}.txt"
    from core.paths import user_desktop_dir

    desktop  = user_desktop_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / filename

    header = (
        f"ONYX — YouTube Summary\n"
        f"{'─' * 50}\n"
        f"URL    : {video_url}\n"
        f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'─' * 50}\n\n"
    )
    filepath.write_text(header + content, encoding="utf-8")

    try:
        if is_windows():
            subprocess.Popen(["notepad.exe", str(filepath)])
        elif is_mac():
            subprocess.Popen(["open", "-t", str(filepath)])
        else:
            subprocess.Popen(["xdg-open", str(filepath)])
    except Exception as e:
        print(f"[YouTube] ⚠️ Could not open text editor: {e}")

    return str(filepath)


def _scrape_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        info = {}

        for key, pattern in [
            ("title",    r'"title":\{"runs":\[\{"text":"([^"]+)"'),
            ("channel",  r'"ownerChannelName":"([^"]+)"'),
            ("views",    r'"viewCount":"(\d+)"'),
            ("duration", r'"lengthSeconds":"(\d+)"'),
            ("likes",    r'"label":"([0-9,]+ likes)"'),
        ]:
            match = re.search(pattern, html)
            if match:
                raw = match.group(1)
                if key == "views":
                    info[key] = f"{int(raw):,}"
                elif key == "duration":
                    secs = int(raw)
                    info[key] = f"{secs // 60}:{secs % 60:02d}"
                else:
                    info[key] = raw

        return info
    except Exception as e:
        print(f"[YouTube] ⚠️ Info scrape failed: {e}")
        return {}


def _owner_region(default: str = "US") -> str:
    """The owner's own country, not a build-time default.

    Trending was pinned to "TR", so an owner in any other country received
    another region's videos and no error to explain why.
    """
    import locale

    # Windows reports "English_United States", not "en_US", so the BCP-47 tag
    # from the OS is asked for first and the POSIX-style tag is the fallback.
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, 85):
            tag = buffer.value  # e.g. "en-US"
            if "-" in tag:
                country = tag.rsplit("-", 1)[1][:2].upper()
                if len(country) == 2 and country.isalpha():
                    return country
    except (AttributeError, OSError, ValueError, IndexError):
        pass
    try:
        tag = locale.getdefaultlocale()[0] or ""
        if "_" in tag:
            country = tag.rsplit("_", 1)[1][:2].upper()
            if len(country) == 2 and country.isalpha():
                return country
    except (AttributeError, ValueError, IndexError):
        pass
    return default


def _scrape_trending(region: str | None = None, max_results: int = 8) -> list[dict]:
    region = region or _owner_region()
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=12)
        response.raise_for_status()
        return _video_results(response.text, max_results)
    except Exception as e:
        print(f"[YouTube] ⚠️ Trending scrape failed: {e}")
        return []

def _handle_play(parameters: dict, player) -> str:
    query = parameters.get("query", "").strip()
    if not query:
        return "Please tell me what you'd like to watch, sir."

    if player:
        player.write_log(f"[YouTube] Searching: {query}")

    print(f"[YouTube] 🔍 Scraping first non-Shorts video for: {query}")

    video_url = _scrape_first_video_url(query)

    if video_url:
        print(f"[YouTube] ▶️ Opening: {video_url}")
        _open_url(video_url)
        return f"Playing: {query}"

    print("[YouTube] ⚠️ Scrape failed, opening filtered search page")
    fallback_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}"
        f"&sp={_YT_VIDEO_FILTER}"
    )
    _open_url(fallback_url)
    return f"Opened YouTube search for: {query} (manual selection required)"


def _handle_search(parameters: dict, player, speak) -> str:
    query = str(parameters.get("query") or "").strip()
    if not query:
        return "Please tell me what you'd like to search for, sir."
    limit = _bounded_result_count(parameters.get("max_results"), default=5)
    if player:
        player.write_log(f"[YouTube] Searching: {query}")
    results = _scrape_search_results(query, max_results=limit)
    if results:
        lines = [f"YouTube search results for {query}:"]
        lines.extend(
            f"{item['rank']}. {item['title']} — {item['channel']}\n{item['url']}"
            for item in results
        )
        return "\n".join(lines)
    fallback_url = (
        "https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    )
    _open_url(fallback_url)
    return f"Could not parse YouTube results; opened the search page for: {query}"


def _handle_summarize(parameters: dict, player, speak) -> str:
    if not _TRANSCRIPT_OK:
        return "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"

    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url:
        return "No URL provided, sir. Summary cancelled."
    if not _is_valid_youtube_url(url):
        return "That doesn't appear to be a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, sir."

    if player:
        player.write_log(f"[YouTube] Summarizing: {url}")
    if speak:
        speak("Fetching the transcript now, sir. One moment.")

    transcript = _get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, sir."

    if speak:
        speak("Transcript retrieved. Generating summary now.")

    try:
        summary = _summarize_with_gemini(transcript, url)
    except Exception as e:
        return f"Summary generation failed, sir: {e}"

    if speak:
        speak(summary)

    if parameters.get("save", False):
        saved_path = _save_summary(summary, url)
        return f"Summary complete and saved to Desktop: {saved_path}"

    return summary


def _handle_get_info(parameters: dict, player, speak) -> str:
    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url or not _is_valid_youtube_url(url):
        return "Please provide a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID, sir."

    if player:
        player.write_log(f"[YouTube] Getting info: {url}")

    info = _scrape_video_info(video_id)
    if not info:
        return "Could not retrieve video information, sir."

    lines = [
        f"{key.capitalize()}: {info[key]}"
        for key in ("title", "channel", "views", "duration", "likes")
        if key in info
    ]
    result = "\n".join(lines)

    if speak:
        speak(f"Here's the video info, sir. {result.replace(chr(10), '. ')}")

    return result


def _handle_trending(parameters: dict, player, speak) -> str:
    region = str(parameters.get("region") or _owner_region()).upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        return "Please provide a valid two-letter region code, sir."

    if player:
        player.write_log(f"[YouTube] Trending: {region}")

    limit = _bounded_result_count(parameters.get("max_results"), default=8)
    trending = _scrape_trending(region=region, max_results=limit)
    if not trending:
        return f"Could not fetch trending videos for region {region}, sir."

    lines  = [f"Top trending videos in {region}:"]
    lines += [f"{v['rank']}. {v['title']} — {v['channel']}" for v in trending]
    result = "\n".join(lines)

    if speak:
        top3   = trending[:3]
        spoken = "Here are the top trending videos, sir. " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)

    return result

_ACTION_MAP = {
    "play":      _handle_play,
    "search":    _handle_search,
    "summarize": _handle_summarize,
    "get_info":  _handle_get_info,
    "trending":  _handle_trending,
}


def youtube_video(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "play").lower().strip()

    if player:
        player.write_log(f"[YouTube] Action: {action}")
    print(f"[YouTube] ▶️  Action: {action}  Params: {params}")

    handler = _ACTION_MAP.get(action)
    if handler is None:
        return (
            f"Unknown YouTube action: '{action}'. "
            "Available: play, search, summarize, get_info, trending."
        )

    try:
        if action == "play":
            return handler(params, player) or "Done."
        return handler(params, player, speak) or "Done."
    except Exception as e:
        print(f"[YouTube] ❌ Error in {action}: {e}")
        return f"YouTube {action} failed, sir: {e}"
