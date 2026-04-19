from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

app = FastAPI()


class SearchRequest(BaseModel):
    lang: str
    query: str
    forums: List[str] = []


FORUM_DOMAIN_MAP: Dict[str, str] = {
    "drive2": "drive2.ru",
    "drom": "forums.drom.ru",
    "auto_ru": "forum.auto.ru",
    "pistonheads": "pistonheads.com",
    "grassroots": "grassrootsmotorsports.com",
    "jdmvip": "jdmvip.com",
    "bobistheoilguy": "bobistheoilguy.com",
    "minkara": "minkara.carview.co.jp",
    "carview": "carview.yahoo.co.jp",
    "autohome": "autohome.com.cn",
    "xcar_cn": "club.xcar.com.cn",
    "pcauto": "pcauto.com.cn",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@app.get("/")
def home():
    return {"message": "Car Diagnostic API is working"}


def ddg_search(query: str, max_results: int = 5):
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    for a in soup.select("a.result__a"):
        title = a.get_text(" ", strip=True)
        link = a.get("href")
        if not link:
            continue

        results.append(
            {
                "title": title,
                "url": link,
            }
        )

        if len(results) >= max_results:
            break

    return results


@app.post("/search")
def search(data: SearchRequest):
    all_results = []

    for forum in data.forums:
        domain = FORUM_DOMAIN_MAP.get(forum)
        if not domain:
            continue

        search_query = f"site:{domain} {data.query}"

        try:
            found = ddg_search(search_query, max_results=3)
            for item in found:
                all_results.append(
                    {
                        "forum": forum,
                        "domain": domain,
                        "search_query": search_query,
                        "title": item["title"],
                        "url": item["url"],
                        "post": "",
                        "comments": [],
                    }
                )
        except Exception as e:
            all_results.append(
                {
                    "forum": forum,
                    "domain": domain,
                    "search_query": search_query,
                    "title": f"Search error: {str(e)}",
                    "url": "",
                    "post": "",
                    "comments": [],
                }
            )

    return {"results": all_results}
