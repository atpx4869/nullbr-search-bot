import os
import asyncio
import httpx
import logging
import sqlite3
import random
import time
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class NullbrAPI:
    def __init__(self, base_url: str = "https://api.nullbr.eu.org"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            timeout=20.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        )
        self._credentials_cache: List[Tuple[str, str]] = []
        self._credentials_cache_at = 0.0
        self._credentials_ttl = int(os.getenv("CREDENTIALS_CACHE_TTL", "60"))
        self._meta_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._meta_ttl = int(os.getenv("META_CACHE_TTL", "30"))
        self._meta_cache_max = int(os.getenv("META_CACHE_MAX", "512"))
        self._request_semaphore = asyncio.Semaphore(int(os.getenv("API_MAX_CONCURRENCY", "20")))
        self._metrics = {
            "requests_total": 0,
            "requests_meta": 0,
            "requests_res": 0,
            "requests_user": 0,
            "meta_cache_hit": 0,
            "meta_cache_miss": 0,
            "http_429": 0,
            "http_errors": 0,
            "request_errors": 0,
            "latency_ms_sum": 0.0,
        }

    def invalidate_credentials_cache(self):
        self._credentials_cache = []
        self._credentials_cache_at = 0.0

    def _load_credentials_from_db(self) -> List[Tuple[str, str]]:
        try:
            with sqlite3.connect("auth.db") as conn:
                c = conn.cursor()
                c.execute("SELECT app_id, api_key FROM api_keys")
                return c.fetchall()
        except Exception as e:
            logger.error("Error reading API keys from DB: %s", e)
            return []

    def _env_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        app_id = os.getenv("X_APP_ID") or os.getenv("NULLBR_APP_ID")
        api_key = os.getenv("X_API_KEY") or os.getenv("NULLBR_API_KEY")
        return app_id, api_key

    def _get_credentials(self) -> Tuple[str, str]:
        """Pick one AppID/APIKey pair from DB cache, fallback to .env."""
        now = time.time()
        if now - self._credentials_cache_at > self._credentials_ttl or not self._credentials_cache:
            self._credentials_cache = self._load_credentials_from_db()
            self._credentials_cache_at = now

        if self._credentials_cache:
            return random.choice(self._credentials_cache)

        app_id, api_key = self._env_credentials()
        if not app_id or not api_key:
            raise ValueError("No API credentials found in database or .env file.")
        return app_id, api_key

    @staticmethod
    def _build_meta_cache_key(endpoint: str, params: Optional[Dict[str, Any]]) -> str:
        if not params:
            return endpoint
        items = sorted((str(k), str(v)) for k, v in params.items())
        return f"{endpoint}?" + "&".join(f"{k}={v}" for k, v in items)

    async def _request(self, endpoint: str, auth_mode: str = "meta", params: Optional[Dict[str, Any]] = None):
        self._metrics["requests_total"] += 1
        if auth_mode == "meta":
            self._metrics["requests_meta"] += 1
        elif auth_mode == "res":
            self._metrics["requests_res"] += 1
        elif auth_mode == "user":
            self._metrics["requests_user"] += 1

        app_id, api_key = self._get_credentials()

        headers = {"X-APP-ID": app_id}
        if auth_mode in ("res", "user"):
            headers["X-API-KEY"] = api_key

        cache_key = None
        if auth_mode == "meta":
            cache_key = self._build_meta_cache_key(endpoint, params)
            cached = self._meta_cache.get(cache_key)
            if cached and (time.time() - cached[0] <= self._meta_ttl):
                self._metrics["meta_cache_hit"] += 1
                return cached[1]
            self._metrics["meta_cache_miss"] += 1

        try:
            started_at = time.perf_counter()
            async with self._request_semaphore:
                response = await self.client.get(f"{self.base_url}{endpoint}", headers=headers, params=params)
            response.raise_for_status()
            self._metrics["latency_ms_sum"] += (time.perf_counter() - started_at) * 1000
            data = response.json()
            if auth_mode == "meta" and cache_key:
                if len(self._meta_cache) >= self._meta_cache_max:
                    oldest = min(self._meta_cache, key=lambda k: self._meta_cache[k][0])
                    self._meta_cache.pop(oldest, None)
                self._meta_cache[cache_key] = (time.time(), data)
            return data
        except httpx.RequestError as e:
            self._metrics["request_errors"] += 1
            logger.error("API request failed: %s", e)
            return None
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else "unknown"
            self._metrics["http_errors"] += 1
            if status == 429:
                self._metrics["http_429"] += 1
            logger.error("API HTTP status error (%s): %s", status, e)
            return None

    def get_metrics_snapshot(self, reset: bool = False) -> Dict[str, Any]:
        data = dict(self._metrics)
        total_for_avg = data["requests_total"] - data["meta_cache_hit"]
        data["latency_ms_avg"] = round((data["latency_ms_sum"] / total_for_avg), 2) if total_for_avg > 0 else 0.0
        data["meta_cache_size"] = len(self._meta_cache)
        if reset:
            self._metrics = {
                "requests_total": 0,
                "requests_meta": 0,
                "requests_res": 0,
                "requests_user": 0,
                "meta_cache_hit": 0,
                "meta_cache_miss": 0,
                "http_429": 0,
                "http_errors": 0,
                "request_errors": 0,
                "latency_ms_sum": 0.0,
            }
        return data

    # --- META APIs ---
    async def search(self, query, page=1):
        """搜索影视"""
        return await self._request("/search", params={"query": query, "page": page})
        
    async def get_movie_info(self, tmdbid):
        """获取电影信息"""
        return await self._request(f"/movie/{tmdbid}")
        
    async def get_tv_info(self, tmdbid):
        """获取剧集信息"""
        return await self._request(f"/tv/{tmdbid}")
        
    async def get_person_info(self, tmdbid):
        """获取人物信息"""
        return await self._request(f"/person/{tmdbid}")
        
    async def get_collection_info(self, tmdbid):
        """获取合集信息"""
        return await self._request(f"/collection/{tmdbid}")

    # --- RES APIs ---
    async def get_movie_115(self, tmdbid):
        """获取电影115网盘资源"""
        return await self._request(f"/movie/{tmdbid}/115", auth_mode="res")
        
    async def get_movie_magnet(self, tmdbid):
        """获取电影磁力资源"""
        return await self._request(f"/movie/{tmdbid}/magnet", auth_mode="res")

    async def get_tv_115(self, tmdbid):
        """获取剧集115网盘资源"""
        return await self._request(f"/tv/{tmdbid}/115", auth_mode="res")

    async def get_tv_season_magnet(self, tmdbid, season_num):
        """获取剧集整季磁力资源"""
        return await self._request(f"/tv/{tmdbid}/season/{season_num}/magnet", auth_mode="res")

    async def get_tv_episode_magnet(self, tmdbid, season_num, episode_num):
        """获取剧集单集磁力资源"""
        return await self._request(
            f"/tv/{tmdbid}/season/{season_num}/episode/{episode_num}/magnet",
            auth_mode="res",
        )
        
    async def get_user_info(self):
        """获取用户信息（订阅及配额）"""
        return await self._request("/user/info", auth_mode="user")
            
    async def close(self):
        """关闭 HTTPX 客户端"""
        await self.client.aclose()
