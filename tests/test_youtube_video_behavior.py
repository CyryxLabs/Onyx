from __future__ import annotations

import json
from unittest.mock import Mock, patch

import actions.youtube_video as youtube


def _page(*renderers: dict) -> str:
    data = {"contents": [{"videoRenderer": renderer} for renderer in renderers]}
    return f"<script>var ytInitialData = {json.dumps(data)};</script>"


def _renderer(video_id: str, title: str, channel: str = "Channel") -> dict:
    return {
        "videoId": video_id,
        "title": {"runs": [{"text": title}]},
        "ownerText": {"runs": [{"text": channel}]},
    }


def test_search_is_dispatched_and_returns_bounded_video_renderers() -> None:
    html = _page(
        *(_renderer(f"video{i:06d}", f"Real video {i}") for i in range(10))
    )
    response = Mock(text=html)
    response.raise_for_status.return_value = None
    with (
        patch.object(youtube.requests, "get", return_value=response),
        patch.object(youtube, "_open_url") as opened,
    ):
        result = youtube.youtube_video({"action": "search", "query": "onyx", "max_results": 2})
    assert "Real video 0" in result
    assert "Real video 1" in result
    assert "Real video 2" not in result
    opened.assert_not_called()


def test_search_malformed_payload_opens_bounded_fallback_and_does_not_false_pass() -> None:
    response = Mock(text='<script>var ytInitialData = {"broken":;</script>')
    response.raise_for_status.return_value = None
    with (
        patch.object(youtube.requests, "get", return_value=response),
        patch.object(youtube, "_open_url") as opened,
    ):
        result = youtube.youtube_video({"action": "search", "query": "a b"})
    assert result.startswith("Could not parse YouTube results")
    opened.assert_called_once()
    assert "search_query=a+b" in opened.call_args.args[0]


def test_trending_uses_owner_region_and_ignores_page_chrome_titles() -> None:
    html = (
        '<div>{"title":{"runs":[{"text":"Explore"}]}}</div>'
        + _page(_renderer("abcdefghijk", "Actual video", "Actual owner"))
    )
    response = Mock(text=html)
    response.raise_for_status.return_value = None
    with (
        patch.object(youtube, "_owner_region", return_value="CA"),
        patch.object(youtube.requests, "get", return_value=response) as get,
    ):
        result = youtube.youtube_video({"action": "trending", "max_results": 50})
    assert "Actual video" in result
    assert "Actual owner" in result
    assert "Explore" not in result
    assert "gl=CA" in get.call_args.args[0]


def test_trending_network_failure_is_reported_honestly_without_opening() -> None:
    with (
        patch.object(youtube.requests, "get", side_effect=TimeoutError("offline")),
        patch.object(youtube, "_open_url") as opened,
    ):
        result = youtube.youtube_video({"action": "trending", "region": "US"})
    assert result == "Could not fetch trending videos for region US, sir."
    opened.assert_not_called()


def test_trending_rejects_malformed_region_before_network() -> None:
    with patch.object(youtube.requests, "get") as get:
        result = youtube.youtube_video({"action": "trending", "region": "USA"})
    assert result == "Please provide a valid two-letter region code, sir."
    get.assert_not_called()
