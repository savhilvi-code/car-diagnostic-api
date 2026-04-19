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


def domain_matches(url: str, domain: str) -> bool:
    if not url or not domain:
        return False
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return domain in host
    except Exception:
        return False


def ddg_search(query: str, max_results: int = 10):
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


def search_for_forum(query: str, forum: str, domain: str, lang: str):
    """
    Strategy:
    1. Soft search by original query
    2. Filter by forum domain
    3. If empty, fallback search with 'forum' / 'форум'
    4. If still empty, fallback with site:domain
    """
    debug = {
        "forum": forum,
        "domain": domain,
        "query_original": query,
        "attempts": [],
    }

    all_found = []

    # Attempt 1: soft search
    q1 = query
    try:
        raw1 = ddg_search(q1, max_results=10)
        filtered1 = [x for x in raw1 if domain_matches(x["url"], domain)]
        debug["attempts"].append({
            "query": q1,
            "raw_found": len(raw1),
            "filtered_found": len(filtered1),
            "mode": "soft",
        })
        all_found.extend(filtered1)
    except Exception as e:
        debug["attempts"].append({
            "query": q1,
            "raw_found": 0,
            "filtered_found": 0,
            "mode": "soft",
            "error": str(e),
        })

    # Attempt 2: forum keyword
    if not all_found:
        forum_word = "форум" if lang == "ru" else "forum"
        q2 = f"{query} {forum_word}"
        try:
            raw2 = ddg_search(q2, max_results=10)
            filtered2 = [x for x in raw2 if domain_matches(x["url"], domain)]
            debug["attempts"].append({
                "query": q2,
                "raw_found": len(raw2),
                "filtered_found": len(filtered2),
                "mode": "forum_keyword",
            })
            all_found.extend(filtered2)
        except Exception as e:
            debug["attempts"].append({
                "query": q2,
                "raw_found": 0,
                "filtered_found": 0,
                "mode": "forum_keyword",
                "error": str(e),
            })

    # Attempt 3: strict site search
    if not all_found:
        q3 = f"site:{domain} {query}"
        try:
            raw3 = ddg_search(q3, max_results=10)
            filtered3 = [x for x in raw3 if domain_matches(x["url"], domain)]
            debug["attempts"].append({
                "query": q3,
                "raw_found": len(raw3),
                "filtered_found": len(filtered3),
                "mode": "strict_site",
            })
            all_found.extend(filtered3)
        except Exception as e:
            debug["attempts"].append({
                "query": q3,
                "raw_found": 0,
                "filtered_found": 0,
                "mode": "strict_site",
                "error": str(e),
            })

    # Remove duplicates by URL
    dedup = []
    seen = set()
    for item in all_found:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        dedup.append(item)

    return dedup[:5], debug


def fetch_soup(url: str):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def first_nonempty_text(soup: BeautifulSoup, selectors: List[str], min_len: int = 50) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = clean_text(el.get_text(" ", strip=True))
            if len(text) >= min_len:
                return text
    return ""


def many_texts(soup: BeautifulSoup, selectors: List[str], limit: int = 10, min_len: int = 25) -> List[str]:
    items = []
    seen = set()

    for sel in selectors:
        for el in soup.select(sel):
            text = clean_text(el.get_text(" ", strip=True))
            if len(text) < min_len:
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

    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

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
        ], min_len=100)

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1500] for c in comments],
    }


def parse_drom_page(url: str):
    soup = fetch_soup(url)

    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

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
        ], min_len=100)

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1500] for c in comments[:8]],
    }


def parse_auto_ru_page(url: str):
    soup = fetch_soup(url)

    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

    post = first_nonempty_text(soup, [
        ".messageText",
        ".message-content",
        ".post-message",
        ".topic__text",
        ".forum-message",
        "article",
    ])

    comments = many_texts(soup, [
        ".messageText",
        ".message-content",
        ".post-message",
        ".forum-message",
    ], limit=10)

    if comments and post and comments[0] == post:
        comments = comments[1:]

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1500] for c in comments[:8]],
    }


def parse_generic_page(url: str):
    soup = fetch_soup(url)

    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

    post = first_nonempty_text(soup, [
        "article",
        "main",
        ".content",
        "#content",
        ".post",
        ".message",
        ".entry-content",
        "body",
    ], min_len=100)

    comments = many_texts(soup, [
        '[class*="comment"]',
        '[class*="reply"]',
        '[class*="message"]',
    ], limit=8, min_len=40)

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
        if forum == "drom":
            return parse_drom_page(url)
        if forum == "auto_ru":
            return parse_auto_ru_page(url)
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
    debug_forums = []

    for forum in data.forums:
        domain = FORUM_DOMAIN_MAP.get(forum)
        if not domain:
            debug_forums.append({
                "forum": forum,
                "domain": "",
                "skipped": True,
                "reason": "unknown_forum",
            })
            continue

        try:
            found_links, debug_info = search_for_forum(
                query=data.query,
                forum=forum,
                domain=domain,
                lang=data.lang,
            )
            debug_forums.append(debug_info)

            for item in found_links:
                page_data = parse_forum_page(item["url"], forum)

                all_results.append({
                    "forum": forum,
                    "domain": domain,
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "title_from_page": page_data.get("title_from_page", ""),
                    "post": page_data.get("post", ""),
                    "comments": page_data.get("comments", []),
                    "parse_error": page_data.get("parse_error", ""),
                })

        except Exception as e:
            debug_forums.append({
                "forum": forum,
                "domain": domain,
                "query_original": data.query,
                "fatal_error": str(e),
            })

    return {
        "query": data.query,
        "lang": data.lang,
        "forums_requested": data.forums,
        "results_count": len(all_results),
        "debug_forums": debug_forums,
        "results": all_results,
    }
