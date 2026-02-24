import asyncio
import json
from nullbr_api import NullbrAPI

async def main():
    api = NullbrAPI()
    res = await api.get_movie_info("1726") # 钢铁侠 tmdbid
    with open("res_detail.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    await api.close()

asyncio.run(main())
