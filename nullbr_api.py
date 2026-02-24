import os
import httpx
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("NULLBR_APP_ID")
API_KEY = os.getenv("NULLBR_API_KEY")
BASE_URL = "https://api.nullbr.eu.org"

class NullbrAPI:
    def __init__(self):
        self.headers_meta = {
            "X-APP-ID": APP_ID
        }
        self.headers_res = {
            "X-APP-ID": APP_ID,
            "X-API-KEY": API_KEY
        }
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)

    async def _request(self, endpoint, is_res=False, params=None):
        headers = self.headers_res if is_res else self.headers_meta
        try:
            response = await self.client.get(endpoint, headers=headers, params=params)
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
