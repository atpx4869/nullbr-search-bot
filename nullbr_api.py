import os
import httpx
import json
import logging
import sqlite3
import random
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class NullbrAPI:
    def __init__(self, base_url: str = "https://api.nullbr.eu.org"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        
    def _get_credentials(self):
        """Randomly pick an AppID and APIKey from the database for load balancing."""
        try:
            conn = sqlite3.connect("auth.db")
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS api_keys (app_id TEXT, api_key TEXT)")
            c.execute("SELECT app_id, api_key FROM api_keys")
            keys = c.fetchall()
            conn.close()
            
            if keys:
                return random.choice(keys)
        except Exception as e:
            logger.error(f"Error reading API keys from DB: {e}")
            
        # Fallback to pure .env if db missing or empty
        app_id = os.getenv("NULLBR_APP_ID")
        api_key = os.getenv("NULLBR_API_KEY")
        if not app_id or not api_key:
            raise ValueError("No API credentials found in database or .env file.")
        
        return app_id, api_key

    async def _request(self, endpoint, is_res=False, params=None):
        app_id, api_key = self._get_credentials()
        
        headers_meta = {
            "X-APP-ID": app_id
        }
        headers_res = {
            "X-APP-ID": app_id,
            "X-API-KEY": api_key
        }
        
        headers = headers_res if is_res else headers_meta
        try:
            response = await self.client.get(f"{self.base_url}{endpoint}", headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"API Request failed: {e}")
            return None
        except httpx.HTTPStatusError as e:
            print(f"API HTTP Status Error: {e}")
            return None

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
        return await self._request(f"/movie/{tmdbid}/115", is_res=True)
        
    async def get_movie_magnet(self, tmdbid):
        """获取电影磁力资源"""
        return await self._request(f"/movie/{tmdbid}/magnet", is_res=True)

    async def get_tv_115(self, tmdbid):
        """获取剧集115网盘资源"""
        return await self._request(f"/tv/{tmdbid}/115", is_res=True)
        
    async def get_user_info(self):
        """获取用户信息（订阅及配额）"""
        try:
            response = await self.client.get("/user/info", headers=self.headers_res)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"User Info API Request failed: {e}")
            return None
            
    async def close(self):
        """关闭 HTTPX 客户端"""
        await self.client.aclose()
