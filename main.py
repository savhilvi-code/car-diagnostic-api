from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse, parse_qs, unquote
import re

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
    "Accept-Language": "ru,en-US;q=0.9,en;q=0.8",
}


@app.get("/")
def home():
    return {"message": "Car Diagnostic API is working"}


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_real_url(link: str) -> str:
    """
    DuckDuckGo sometimes returns redirect links like /l/?uddg=...
    This function extracts the real URL if needed.
    """
    if not link:
        return ""

    if link.startswith("//"):
        return "https:" + link

    if link.startswith("/l/?") or "duckduckgo.com/l/?" in link:
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        if uddg:
            return unquote(uddg[0])

    return link


def ddg_search(query: str, max_results: int = 5):
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    for a in soup.select("a.result__a"):
        title = clean_text(a.get_text(" ", strip=True))
        link = extract_real_url(a.get("href", ""))

        if not link:
            continue

        results.append({
            "title": title,
            "url": link,
        })

        if len(results) >= max_results:
            break

    return results


def fetch_soup(url: str):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def first_nonempty_text(soup: BeautifulSoup, selectors: List[str]) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = clean_text(el.get_text(" ", strip=True))
            if len(text) > 50:
                return text
    return ""


def many_texts(soup: BeautifulSoup, selectors: List[str], limit: int = 10) -> List[str]:
    items = []
    seen = set()

    for sel in selectors:
        for el in soup.select(sel):
            text = clean_text(el.get_text(" ", strip=True))
            if len(text) < 25:
                continue
            if text in seen:
                continue
            seen.add(text)
            items.append(text)
            if len(items) >= limit:
                return items

    return items


def parse_drive2_page(url: str):
    soup = fetch_soup(url)

    title = ""
    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

    post = first_nonempty_text(soup, [
        "article",
        ".c-post__body",
        ".c-post__content",
        ".c-entry-content",
        ".post-content",
        ".js-content",
        '[class*="content"]',
    ])

    comments = many_texts(soup, [
        ".c-comment__body",
        ".c-comment__text",
        ".comment__text",
        ".comment__body",
        '[class*="comment"] [class*="text"]',
        '[class*="comment"] [class*="body"]',
    ], limit=8)

    if not post:
        post = first_nonempty_text(soup, [
            "main",
            ".content",
            "#content",
            "body",
        ])

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1500] for c in comments],
    }


def parse_drom_page(url: str):
    soup = fetch_soup(url)

    title = ""
    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

    post = first_nonempty_text(soup, [
        ".message-content",
        ".messageContent",
        ".post_message",
        ".b-post__content",
        ".messageBody",
        ".topic-body",
        "article",
    ])

    comments = many_texts(soup, [
        ".message-content",
        ".messageContent",
        ".post_message",
        ".messageBody",
        ".b-post__content",
    ], limit=10)

    # very often first item = main post, rest = replies
    if comments and post and comments[0] == post:
        comments = comments[1:]

    if not post and comments:
        post = comments[0]
        comments = comments[1:]

    if not post:
        post = first_nonempty_text(soup, [
            "main",
            ".content",
            "#content",
            "body",
        ])

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1500] for c in comments[:8]],
    }


def parse_generic_page(url: str):
    soup = fetch_soup(url)

    title = ""
    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

    post = first_nonempty_text(soup, [
        "article",
        "main",
        ".content",
        "#content",
        ".post",
        ".message",
        ".entry-content",
        "body",
    ])

    comments = many_texts(soup, [
        '[class*="comment"]',
        '[class*="reply"]',
        '[class*="message"]',
    ], limit=8)

    if comments and post and comments[0] == post:
        comments = comments[1:]

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1500] for c in comments],
    }


def parse_forum_page(url: str, forum: str):
    try:
        if forum == "drive2":
            return parse_drive2_page(url)
        elif forum == "drom":
            return parse_drom_page(url)
        else:
            return parse_generic_page(url)
    except Exception as e:
        return {
            "title_from_page": "",
            "post": "",
            "comments": [],
            "parse_error": str(e),
        }


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
                page_data = parse_forum_page(item["url"], forum)

                all_results.append({
                    "forum": forum,
                    "domain": domain,
                    "search_query": search_query,
                    "title": item["title"],
                    "url": item["url"],
                    "post": page_data.get("post", ""),
                    "comments": page_data.get("comments", []),
                    "title_from_page": page_data.get("title_from_page", ""),
                    "parse_error": page_data.get("parse_error", ""),
                })

        except Exception as e:
            all_results.append({
                "forum": forum,
                "domain": domain,
                "search_query": search_query,
                "title": f"Search error: {str(e)}",
                "url": "",
                "post": "",
                "comments": [],
                "title_from_page": "",
                "parse_error": str(e),
            })

    return {
        "query": data.query,
        "lang": data.lang,
        "results_count": len(all_results),
        "results": all_results,
    }
