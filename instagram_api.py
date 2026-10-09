"""
Minimal async client for the Instagram Graph API ("Instagram API with
Instagram Login", host graph.instagram.com).

Covers what the Instagram manager needs: profile + media + insights for the
analysis, resumable Reels upload and publishing, comments, and long-lived
token refresh.
"""

import asyncio
import logging
import os

import httpx

log = logging.getLogger("instagram_api")

GRAPH_HOST = os.environ.get("IG_GRAPH_HOST", "graph.instagram.com")
API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
RUPLOAD_URL = "https://rupload.facebook.com/ig-api-upload/{version}/{container_id}"

MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,timestamp,like_count,"
    "comments_count,permalink"
)
# Newest metric names first; older API versions or media types reject some,
# so we fall back to smaller sets.
INSIGHT_METRIC_SETS = [
    "reach,views,likes,comments,shares,saved,total_interactions",
    "reach,likes,comments,shares,saved",
    "reach,likes,comments,saved",
]


class InstagramError(RuntimeError):
    def __init__(self, message: str, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class InstagramAPI:

    def __init__(self, token: str, user_id: str | None = None):
        self.token = token
        self.user_id = user_id
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20))

    # ---------------- transport ----------------

    def url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"https://{GRAPH_HOST}/{API_VERSION}/{path.lstrip('/')}"

    async def request(self, method: str, path: str, params=None, data=None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.token
        last_error = None
        for attempt in range(3):
            try:
                r = await self.http.request(method, self.url(path), params=params, data=data)
            except httpx.TransportError as e:
                last_error = InstagramError(f"network error: {e}")
                await asyncio.sleep(3 * (attempt + 1))
                continue
            try:
                body = r.json()
            except ValueError:
                body = {}
            if r.status_code >= 500 and attempt < 2:
                last_error = InstagramError(f"HTTP {r.status_code}", status=r.status_code)
                await asyncio.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400 or "error" in body:
                err = body.get("error") or {}
                raise InstagramError(
                    err.get("error_user_msg") or err.get("message") or r.text[:300],
                    code=err.get("code"),
                    status=r.status_code,
                )
            return body
        raise last_error

    async def get(self, path, **params):
        return await self.request("GET", path, params=params)

    async def post(self, path, **data):
        return await self.request("POST", path, data=data)

    # ---------------- account ----------------

    async def profile(self) -> dict:
        me = await self.get(
            "me",
            fields="user_id,username,name,biography,followers_count,"
                   "follows_count,media_count,profile_picture_url,website",
        )
        if not self.user_id:
            self.user_id = str(me.get("user_id") or me["id"])
        return me

    async def recent_media(self, limit: int = 30) -> list[dict]:
        uid = self.user_id or "me"
        items, after = [], None
        while len(items) < limit:
            params = {"fields": MEDIA_FIELDS, "limit": min(50, limit - len(items))}
            if after:
                params["after"] = after
            page = await self.get(f"{uid}/media", **params)
            items.extend(page.get("data", []))
            after = page.get("paging", {}).get("cursors", {}).get("after")
            if not after or not page.get("data") or "next" not in page.get("paging", {}):
                break
        return items[:limit]

    async def media_insights(self, media_id: str) -> dict:
        last_error = None
        for metrics in INSIGHT_METRIC_SETS:
            try:
                body = await self.get(f"{media_id}/insights", metric=metrics)
            except InstagramError as e:
                last_error = e
                continue
            result = {}
            for item in body.get("data", []):
                if item.get("values"):
                    value = item["values"][0].get("value", 0)
                else:
                    value = (item.get("total_value") or {}).get("value", 0)
                result[item["name"]] = value if isinstance(value, (int, float)) else 0
            return result
        raise last_error or InstagramError("insights unavailable")

    async def publishing_limit(self) -> dict:
        body = await self.get(
            f"{self.user_id}/content_publishing_limit", fields="quota_usage,config"
        )
        return (body.get("data") or [{}])[0]

    async def refresh_token(self) -> dict:
        """Extend the long-lived token by another 60 days."""
        body = await self.get(
            "https://graph.instagram.com/refresh_access_token",
            grant_type="ig_refresh_token",
        )
        self.token = body["access_token"]
        return body

    # ---------------- publishing ----------------

    async def publish_reel(self, video: bytes, caption: str, thumb_offset_ms: int = 0) -> str:
        """Upload a video as a Reel and publish it. Returns the media id."""
        container = await self.post(
            f"{self.user_id}/media",
            media_type="REELS",
            upload_type="resumable",
            caption=caption,
            share_to_feed="true",
            thumb_offset=str(thumb_offset_ms),
        )
        container_id = container["id"]
        upload_url = container.get("uri") or RUPLOAD_URL.format(
            version=API_VERSION, container_id=container_id
        )
        r = await self.http.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(len(video)),
            },
            content=video,
        )
        if r.status_code >= 400:
            raise InstagramError(f"video upload failed: {r.text[:300]}", status=r.status_code)

        await self.wait_container(container_id)
        published = await self.post(f"{self.user_id}/media_publish", creation_id=container_id)
        return published["id"]

    async def wait_container(self, container_id: str, timeout: int = 900):
        waited = 0
        while waited < timeout:
            body = await self.get(container_id, fields="status_code,status")
            status = body.get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"container {status}: {body.get('status', '')}")
            await asyncio.sleep(10)
            waited += 10
        raise InstagramError("video processing timed out")

    async def permalink(self, media_id: str) -> str:
        body = await self.get(media_id, fields="permalink")
        return body.get("permalink", "")

    # ---------------- comments ----------------

    async def comments(self, media_id: str, limit: int = 50) -> list[dict]:
        body = await self.get(
            f"{media_id}/comments",
            fields="id,text,username,timestamp,replies{username}",
            limit=limit,
        )
        return body.get("data", [])

    async def reply_comment(self, comment_id: str, message: str) -> str:
        body = await self.post(f"{comment_id}/replies", message=message)
        return body.get("id", "")
