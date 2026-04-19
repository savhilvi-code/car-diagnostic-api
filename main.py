from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse, parse_qs, unquote
import re
import random
import time

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


USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",

    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",

    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",

    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",

    # Safari Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",

    # Mobile Safari iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 "
    "Mobile/15E148 Safari/604.1",

    # Mobile Chrome Android
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]


@app.get("/")
def home():
    return {"message": "Car Diagnostic API is working"}


def build_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.7,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = build_session()


def get_headers() -> Dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "ru,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://duckduckgo.com/",
        "DNT": "1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def human_delay(min_s: float = 0.35, max_s: float = 1.1) -> None:
    time.sleep(random.uniform(min_s, max_s))


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
        host = urlparse(url).netloc.lower()
        return domain in host
    except Exception:
        return False


def dedupe_results(items: List[Dict]) -> List[Dict]:
    out = []
    seen = set()

    for item in items:
        url = item.get("url", "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)

    return out


def simplify_query(query: str, lang: str) -> List[str]:
    q = clean_text(query)
    variants = [q]

    stop_ru = [
        "проблема", "проблемы", "с", "на", "и", "или", "при", "машина", "авто",
        "холодным", "холодную", "запуском", "пуском", "причины", "года", "год",
        "двигателем", "двигатель"
    ]
    stop_en = [
        "problem", "issue", "with", "for", "and", "cold", "start", "starting",
        "engine", "year", "model"
    ]

    tokens = q.split()

    if lang == "ru":
        short_tokens = [t for t in tokens if t.lower() not in stop_ru]
    elif lang == "en":
        short_tokens = [t for t in tokens if t.lower() not in stop_en]
    else:
        short_tokens = tokens

    short_q = clean_text(" ".join(short_tokens))
    if short_q and short_q not in variants:
        variants.append(short_q)

    keep_keywords = []
    for t in short_tokens:
        low = t.lower()
        if (
            "nissan" in low
            or "x-trail" in low
            or "xtrail" in low
            or "pnt30" in low
            or "sr20ve" in low
            or "sr20vet" in low
            or "завод" in low
            or "пуск" in low
            or "холод" in low
            or "гуд" in low
            or "cold" in low
            or "start" in low
            or "noise" in low
        ):
            keep_keywords.append(t)

    mini_q = clean_text(" ".join(keep_keywords))
    if mini_q and mini_q not in variants:
        variants.append(mini_q)

    return variants[:3]


def ddg_html_search(query: str, max_results: int = 10) -> List[Dict]:
    human_delay()
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    r = SESSION.get(url, headers=get_headers(), timeout=8)
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
            "source": "ddg_html",
        })

        if len(results) >= max_results:
            break

    return results


def ddg_lite_search(query: str, max_results: int = 10) -> List[Dict]:
    human_delay()
    url = f"https://lite.duckduckgo.com/lite/?q={quote(query)}"
    r = SESSION.get(url, headers=get_headers(), timeout=8)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    for a in soup.select("a"):
        href = a.get("href", "")
        text = clean_text(a.get_text(" ", strip=True))

        if not href or not text:
            continue

        real_url = extract_real_url(href)
        if not real_url.startswith("http"):
            continue

        results.append({
            "title": text,
            "url": real_url,
            "source": "ddg_lite",
        })

        if len(results) >= max_results:
            break

    return results


def search_engine(query: str, max_results: int = 10) -> Tuple[List[Dict], List[Dict]]:
    debug = []
    all_found = []

    try:
        r1 = ddg_html_search(query, max_results=max_results)
        debug.append({
            "engine": "ddg_html",
            "query": query,
            "found": len(r1),
        })
        all_found.extend(r1)
    except Exception as e:
        debug.append({
            "engine": "ddg_html",
            "query": query,
            "found": 0,
            "error": str(e),
        })

    if not all_found:
        try:
            r2 = ddg_lite_search(query, max_results=max_results)
            debug.append({
                "engine": "ddg_lite",
                "query": query,
                "found": len(r2),
            })
            all_found.extend(r2)
        except Exception as e:
            debug.append({
                "engine": "ddg_lite",
                "query": query,
                "found": 0,
                "error": str(e),
            })

    return dedupe_results(all_found), debug


def build_query_variants(query: str, lang: str, domain: str) -> List[Tuple[str, str]]:
    variants = []
    simplified = simplify_query(query, lang)

    for q in simplified:
        variants.append(("soft", q))

    forum_word = "форум" if lang == "ru" else "forum"
    for q in simplified[:2]:
        variants.append(("forum_keyword", f"{q} {forum_word}"))

    for q in simplified[:2]:
        variants.append(("strict_site", f"site:{domain} {q}"))

    out = []
    seen = set()

    for mode, q in variants:
        q = clean_text(q)
        if not q or q in seen:
            continue
        seen.add(q)
        out.append((mode, q))

    return out[:6]


def search_for_forum(query: str, forum: str, domain: str, lang: str):
    debug = {
        "forum": forum,
        "domain": domain,
        "query_original": query,
        "attempts": [],
    }

    collected = []

    for mode, q in build_query_variants(query, lang, domain):
        found, engine_debug = search_engine(q, max_results=10)
        filtered = [x for x in found if domain_matches(x["url"], domain)]

        debug["attempts"].append({
            "mode": mode,
            "query": q,
            "raw_found": len(found),
            "filtered_found": len(filtered),
            "engines": engine_debug,
        })

        collected.extend(filtered)

        if filtered:
            break

    return dedupe_results(collected)[:5], debug


def fetch_soup(url: str):
    human_delay(0.4, 1.3)
    r = SESSION.get(url, headers=get_headers(), timeout=8)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def first_nonempty_text(soup: BeautifulSoup, selectors: List[str], min_len: int = 60) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = clean_text(el.get_text(" ", strip=True))
            if len(text) >= min_len:
                return text
    return ""


def many_texts(soup: BeautifulSoup, selectors: List[str], limit: int = 8, min_len: int = 30) -> List[str]:
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
    ], min_len=80)

    comments = many_texts(soup, [
        ".c-comment__body",
        ".c-comment__text",
        ".comment__text",
        ".comment__body",
        '[class*="comment"] [class*="text"]',
        '[class*="comment"] [class*="body"]',
    ], limit=8, min_len=40)

    if not post:
        post = first_nonempty_text(soup, [
            "main",
            ".content",
            "#content",
            "body",
        ], min_len=150)

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1200] for c in comments],
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
    ], min_len=80)

    comments = many_texts(soup, [
        ".message-content",
        ".messageContent",
        ".post_message",
        ".messageBody",
        ".b-post__content",
    ], limit=10, min_len=40)

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
        ], min_len=150)

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1200] for c in comments[:8]],
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
    ], min_len=80)

    comments = many_texts(soup, [
        ".messageText",
        ".message-content",
        ".post-message",
        ".forum-message",
    ], limit=10, min_len=40)

    if comments and post and comments[0] == post:
        comments = comments[1:]

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1200] for c in comments[:8]],
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
    ], min_len=150)

    comments = many_texts(soup, [
        '[class*="comment"]',
        '[class*="reply"]',
        '[class*="message"]',
    ], limit=8, min_len=60)

    if comments and post and comments[0] == post:
        comments = comments[1:]

    return {
        "title_from_page": title,
        "post": post[:5000],
        "comments": [c[:1200] for c in comments],
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
                    "search_source": item.get("source", ""),
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
