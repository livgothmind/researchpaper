import io
import json
import logging
import re
from urllib.parse import urlparse

import pypdf
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from django.conf import settings
from django.core.cache import cache

from .prompts import CONFERENCE_EXTRACT_PROMPT, CONFERENCE_SIMILAR_PROMPT

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"
    )
}

_openai_key = getattr(settings, "OPENAI_API_KEY", None) or ""
_client = OpenAI(api_key=_openai_key) if _openai_key.strip() else None

_gcs_api_key = getattr(settings, "GOOGLE_CSE_API_KEY", None) or ""
_gcs_cx = getattr(settings, "GOOGLE_CSE_CX", None) or ""

CONF_LABELS = {
    "cvpr": "CVPR", "iccv": "ICCV", "eccv": "ECCV", "wacv": "WACV",
    "miccai": "MICCAI", "isbi": "ISBI", "midl": "MIDL", "ipmi": "IPMI",
}

CACHE_TTL = 60 * 60 * 6

SESSION_HEADER_RE = re.compile(
    r"(?i)(oral|poster|workshop|tutorial|keynote|plenary|session|track)"
)
SCHEDULE_CONTEXT_RE = re.compile(
    r"(?i)(room[:\s]|\d{1,2}[.:]\d{2}\s*[-–]\s*\d{1,2}[.:]\d{2}|"
    r"poster\s+session|oral\s+session)"
)
POSTER_HALL_RE = re.compile(
    r"(?i)poster\s+hall\s+assign|board\s+id.*poster\s+session"
)
PDF_LINK_RE = re.compile(
    r"program|schedule|accepted|proceedings|book|poster.hall|layout",
    re.IGNORECASE,
)
PAPER_ID_10_RE = re.compile(r"\b(1\d{9})\b")


def search_conference(paper_title, conference, year, day="", tags="",
                      other_conference=""):
    conf_key = conference if conference != "other" else other_conference.strip().lower()
    conf_label = (
        CONF_LABELS.get(conference, conference.upper())
        if conference != "other"
        else other_conference.strip().upper()
    )

    cache_key = f"conf:{conf_key}:{year}:{_norm(paper_title)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    paper_info = None
    similar = []

    for source in _find_program_sources(conf_key, conf_label, year, paper_title):
        try:
            for text in _get_texts_from_source(source["url"], source["type"]):
                if not text or len(text) <= 200:
                    continue
                paper_info = _llm_extract(text, paper_title, conf_label, year, day)
                if paper_info:
                    similar = _llm_similar(text, paper_title, tags, conf_label, year)
                    break
        except Exception as e:
            logger.warning("Source %s failed: %s", source["url"], e)
            continue
        if paper_info:
            break

    result = {"paper": paper_info, "similar": similar}
    cache.set(cache_key, result, timeout=CACHE_TTL)
    return result

def _find_program_sources(conf_key, conf_label, year, paper_title):
    sources = []
    seen = set()

    for url in _get_known_urls(conf_key, year):
        is_pdf = url.lower().endswith(".pdf")
        if is_pdf and not _url_reachable(url):
            continue
        sources.append({"url": url, "type": "pdf" if is_pdf else "html"})
        seen.add(url)

    for r in _google_search(conf_label, year, paper_title):
        if r["url"] not in seen:
            is_pdf = r["url"].lower().endswith(".pdf")
            sources.append({"url": r["url"], "type": "pdf" if is_pdf else "html"})
            seen.add(r["url"])

    return sources


def _get_known_urls(conf_key, year):
    if conf_key in ("cvpr", "iccv", "eccv", "wacv"):
        return [ f"https://{conf_key}.thecvf.com/Conferences/{year}/AcceptedPapers"]
    if conf_key == "miccai":
        return [ f"https://conferences.miccai.org/{year}/files/downloads/MICCAI{year}-Program-Book.pdf"]
    if conf_key == "isbi":
        short = str(year)[2:]
        return [
            f"https://biomedicalimaging.org/{year}/full-program/",
            f"https://biomedicalimaging.org/{year}/technical-program/",
            f"https://biomedicalimaging.org/{year}/isbi{short}-technical-program/",
            f"https://biomedicalimaging.org/{year}/program/",
        ]
    return []


def _google_search(conf_label, year, paper_title):
    queries = [
        f'"{paper_title}" {conf_label} {year}',
        f"{conf_label} {year} program schedule",
    ]
    cl = conf_label.upper()
    if cl == "ISBI":
        queries.append(f"site:biomedicalimaging.org {year} program")
    elif cl == "MICCAI":
        queries.append(f"MICCAI {year} program book filetype:pdf")

    results = []
    for q in queries:
        results.extend(_google_cse(q))

    seen = set()
    unique = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    return unique


def _google_cse(query, limit=5):
    if not _gcs_api_key or not _gcs_cx:
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": _gcs_api_key, "cx": _gcs_cx,
                    "q": query, "num": min(limit, 10)},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Google CSE failed: %s", e)
        return []
    return [
        {"url": item["link"], "title": item.get("title", "")}
        for item in data.get("items", []) if item.get("link")
    ]

def _get_texts_from_source(url, stype):
    if stype == "pdf":
        text = _download_pdf(url)
        return [text] if text else []

    html = _download_html(url)
    if not html:
        return []

    texts = []

    for pdf_url in _extract_pdf_links(html, url):
        text = _download_pdf(pdf_url)
        if text:
            texts.append(text)

    if _is_cvf_page(html):
        text = _extract_cvf_text(html)
        if text:
            texts.append(text)

    if not texts:
        text = _extract_html_text(html)
        if text:
            texts.append(text)

    return texts


def _download_pdf(url):
    cache_key = f"conf:pdf:{_norm(url)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, stream=True)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "pdf" not in ct and not url.lower().endswith(".pdf"):
            return None
        if len(resp.content) > 50 * 1024 * 1024:
            return None

        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        pages = [p.extract_text() for p in reader.pages if p.extract_text()]
        full = "\n".join(pages)[:300_000]

        cache.set(cache_key, full, timeout=CACHE_TTL)
        return full
    except Exception as e:
        logger.warning("PDF failed %s: %s", url, e)
        return None


def _download_html(url):
    cache_key = f"conf:html:{_norm(url)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "html" not in ct and "text" not in ct:
            return None
        cache.set(cache_key, resp.text, timeout=CACHE_TTL)
        return resp.text
    except Exception as e:
        logger.warning("HTML failed %s: %s", url, e)
        return None


def _extract_html_text(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:200_000]


def _extract_pdf_links(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    prioritized, other = [], []

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if not href or not href.lower().endswith(".pdf"):
            continue
        href = _resolve_url(href, base_url)
        link_text = a.get_text(strip=True)
        if PDF_LINK_RE.search(href) or PDF_LINK_RE.search(link_text):
            prioritized.append(href)
        else:
            other.append(href)

    seen = set()
    unique = []
    for u in prioritized + other:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique[:5]


def _resolve_url(href, base_url):
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        p = urlparse(base_url)
        return f"{p.scheme}://{p.netloc}{href}"
    if not href.startswith("http"):
        return base_url.rstrip("/").rsplit("/", 1)[0] + "/" + href
    return href


def _url_reachable(url):
    try:
        r = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def _is_cvf_page(html):
    return bool(
        re.search(r"thecvf\.com", html[:2000], re.IGNORECASE)
        and re.search(r"Accepted\s*Papers", html[:5000], re.IGNORECASE)
    )


CVF_SESSION_RE = re.compile(r"((?:Poster|Oral)\s+Session\s+\S+)")
CVF_HIGHLIGHT_RE = re.compile(r"\s*(Highlight|Award Candidate)\s*$")


def _extract_cvf_text(html):
    soup = BeautifulSoup(html, "lxml")
    lines = _parse_cvf_table(soup) or _parse_cvf_fulltext(soup)
    if not lines:
        return None
    return (
        "CVF Accepted Papers — each line is ONE paper "
        "with its own session and room/booth.\n\n" + "\n".join(lines)
    )


def _parse_cvf_table(soup):
    lines = []
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        left = tds[0].get_text(separator=" ", strip=True)
        right = tds[-1].get_text(separator=" ", strip=True) if len(tds) >= 3 else ""
        if not left or len(left) < 10:
            continue
        m = CVF_SESSION_RE.search(left)
        if not m:
            continue
        title = CVF_HIGHLIGHT_RE.sub("", left[:m.start()]).strip()
        session = m.group(1)
        authors = left[m.end():].strip()
        entry = f"PAPER: {title} | SESSION: {session}"
        if authors:
            entry += f" | AUTHORS: {authors}"
        if right:
            entry += f" | ROOM: {right}"
        lines.append(entry)
    return lines


def _parse_cvf_fulltext(soup):
    text = soup.get_text(separator="\n", strip=True)
    text_lines = text.split("\n")
    paper_re = re.compile(
        r"^(.{15,300}?)\s+(Poster|Oral)\s+Session\s+(\S+)\s*$"
    )
    lines = []
    for i, line in enumerate(text_lines):
        m = paper_re.match(line)
        if not m:
            continue
        title = CVF_HIGHLIGHT_RE.sub("", m.group(1)).strip()
        if len(title) < 10:
            continue
        session = f"{m.group(2)} Session {m.group(3)}"
        authors = ""
        if i + 1 < len(text_lines) and "·" in text_lines[i + 1]:
            authors = text_lines[i + 1].strip()
        entry = f"PAPER: {title} | SESSION: {session}"
        if authors:
            entry += f" | AUTHORS: {authors}"
        lines.append(entry)
    return lines


def _llm_extract(text, paper_title, conf_label, year, day=""):
    if not _client:
        return None

    if len(text) > 120_000:
        text = _smart_chunk(text, paper_title)

    day_clause = f"\nThe user is attending on: {day}" if day else ""

    try:
        resp = _client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": CONFERENCE_EXTRACT_PROMPT},
                {"role": "user", "content": (
                    f"Conference: {conf_label} {year}{day_clause}\n"
                    f"Paper title to find: {paper_title}\n\n"
                    f"--- PROGRAM TEXT ---\n{text}"
                )},
            ],
            max_tokens=500,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        if not data.get("found"):
            return None

        paper_id = data.get("paper_id") or None
        if conf_label.upper() in ("CVPR", "ICCV", "ECCV", "WACV") and paper_id:
            if re.fullmatch(r"\d+", str(paper_id).strip()):
                paper_id = None

        return {
            "title":           data.get("title", paper_title),
            "paper_id":        paper_id,
            "session":         data.get("session") or None,
            "room":            data.get("room") or None,
            "time_slot":       data.get("time_slot") or None,
            "poster_board":    data.get("poster_board") or None,
            "authors":         data.get("authors") or None,
            "partial":         data.get("partial", False),
            "partial_message": data.get("partial_message") or None,
        }
    except Exception as e:
        logger.warning("LLM extract failed: %s", e)
        return None


def _llm_similar(text, paper_title, tags, conf_label, year):
    if not _client or not tags:
        return []

    if len(text) > 80_000:
        text = text[:80_000]

    try:
        resp = _client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": CONFERENCE_SIMILAR_PROMPT},
                {"role": "user", "content": (
                    f"Conference: {conf_label} {year}\n"
                    f"Original paper: {paper_title}\n"
                    f"Tags/topics of interest: {tags}\n\n"
                    f"--- PROGRAM TEXT ---\n{text}"
                )},
            ],
            max_tokens=2000,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        if not isinstance(data, list):
            data = data.get("papers", [])

        similar = []
        for p in data[:15]:
            if _norm(p.get("title", "")) == _norm(paper_title):
                continue
            similar.append({
                "title":     p.get("title", ""),
                "authors":   p.get("authors") or "",
                "session":   p.get("session") or None,
                "room":      p.get("room") or None,
                "time_slot": p.get("time_slot") or None,
                "tags":      p.get("tags", []),
            })
        return similar
    except Exception as e:
        logger.warning("LLM similar failed: %s", e)
        return []


def _smart_chunk(text, paper_title):
    lines = text.split("\n")
    title_lower = paper_title.lower()

    candidates = []
    for i, line in enumerate(lines):
        low = line.lower()
        if title_lower[:40] in low or _words_overlap(title_lower, low) > 0.6:
            candidates.append(i)

    if not candidates:
        return text[:80_000]

    paper_line = candidates[0]
    if len(candidates) > 1:
        best = -1
        for idx in candidates:
            window = "\n".join(lines[max(0, idx - 5):idx + 10])
            score = len(SCHEDULE_CONTEXT_RE.findall(window))
            if score > best:
                best = score
                paper_line = idx

    session_start = paper_line
    for i in range(paper_line - 1, -1, -1):
        if SESSION_HEADER_RE.search(lines[i]):
            session_start = i
            break

    chunk_start = max(0, session_start - 5)
    chunk_end = min(len(lines), paper_line + 50)
    main_chunk = "\n".join(lines[chunk_start:chunk_end])

    parts = []

    toc = []
    for i, line in enumerate(lines[:500]):
        if SESSION_HEADER_RE.search(line):
            s, e = max(0, i - 2), min(len(lines), i + 8)
            toc.append("\n".join(lines[s:e]))
    if toc:
        parts.append("=== SESSION HEADERS ===\n" + "\n---\n".join(toc[:20]))

    parts.append("=== PAPER CONTEXT ===\n" + main_chunk)

    for idx in candidates:
        if idx == paper_line:
            continue
        s, e = max(0, idx - 5), min(len(lines), idx + 15)
        window = "\n".join(lines[s:e])
        if SCHEDULE_CONTEXT_RE.search(window):
            parts.append("=== ADDITIONAL MENTION ===\n" + window)
        if len(parts) >= 6:
            break

    hall = _extract_poster_hall(lines, main_chunk)
    if hall:
        parts.append("=== POSTER HALL ASSIGNMENTS ===\n" + hall)

    return "\n\n".join(parts)


def _extract_poster_hall(lines, main_chunk):
    paper_ids = set(PAPER_ID_10_RE.findall(main_chunk))
    if not paper_ids:
        return None

    hall_lines = []
    in_hall = False
    header_line = None

    for line in lines:
        if POSTER_HALL_RE.search(line):
            in_hall = True
            header_line = line
            continue
        if in_hall:
            if not line.strip():
                continue
            if re.search(r"(?i)technical\s+program|keynote|oral\s+session", line):
                in_hall = False
                continue
            hall_lines.append(line)

    if not hall_lines:
        return None

    relevant = []
    if header_line:
        relevant.append(header_line)

    col_header = next(
        (l for l in hall_lines if re.search(r"(?i)board\s*id", l)), None
    )
    if col_header:
        relevant.append(col_header)

    for line in hall_lines:
        if any(pid in line for pid in paper_ids):
            relevant.append(line)

    if len(relevant) <= (2 if col_header else 1):
        return None

    return "\n".join(relevant)

def _norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())[:120]


def _words_overlap(a, b):
    wa = set(re.findall(r"\w{3,}", a))
    wb = set(re.findall(r"\w{3,}", b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa)
