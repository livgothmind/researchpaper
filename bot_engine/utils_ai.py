import base64
import io
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urlparse

import requests
import pypdf
from bs4 import BeautifulSoup
from openai import OpenAI
from django.conf import settings

from .prompts import (
    POSTER_PROMPT,
    WHY_USEFUL_PROMPT,
    DESCRIPTION_FROM_PDF_PROMPT,
    DESCRIPTION_FROM_SCRAPE_PROMPT,
    build_tag_match_prompt,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"
    )
}

BLOCKED_DOMAINS = {"link.springer.com"}

VALID_SUBFIELDS = {
    "artificial_intelligence", "machine_learning", "deep_learning",
    "reinforcement_learning", "nlp", "expert_systems",
    "knowledge_representation", "generative_model", "continual_learning",
    "foundation_model", "model_merging", "mil",
    "computer_vision", "medical_imaging", "image_processing",
    "computer_graphics", "augmented_reality", "virtual_reality",
    "segmentation", "classification", "vision_text",
    "mri", "cbct", "pet", "xray", "wsi", "ct", "us",
    "distributed_systems", "embedded_systems", "computer_architecture",
    "operating_systems", "parallel_computing", "hpc", "dependable_systems",
    "cybersecurity", "cryptography", "blockchain", "network_security",
    "iot", "edge_computing",
    "data_mining", "big_data", "dbms", "information_retrieval",
    "multimodal", "missing_modalities", "report", "challenge",
    "software_engineering", "algorithm_design", "computational_complexity",
    "formal_methods", "software_testing",
    "cloud_computing", "quantum_computing", "neuromorphic_computing",
    "mobile_computing", "wearable_computing", "pervasive_computing",
    "robotics", "autonomous_systems", "bioinformatics",
    "computational_biology", "hci", "speech_recognition", "signal_processing",
    "smart_grids", "cyber_physical_systems", "brain", "abdomen", "maxillofacial",
}

_SS_API_KEY = getattr(settings, "SEMANTIC_SCHOLAR_API_KEY", None) or ""
_openai_key = getattr(settings, "OPENAI_API_KEY", None) or ""
API_KEY_CONFIGURED = bool(_openai_key.strip())
_openai_client = OpenAI(api_key=_openai_key) if API_KEY_CONFIGURED else None


def _ss_headers():
    return {"x-api-key": _SS_API_KEY} if _SS_API_KEY else {}


def _parse_subfields(raw_subfields):
    if isinstance(raw_subfields, str):
        items = [
            s.strip().lower().replace(" ", "_").replace("-", "_")
            for s in raw_subfields.split(",") if s.strip()
        ]
    elif isinstance(raw_subfields, list):
        items = [
            str(s).strip().lower().replace(" ", "_").replace("-", "_")
            for s in raw_subfields if s
        ]
    else:
        return ""
    seen: set[str] = set()
    valid = []
    for s in items:
        if s in VALID_SUBFIELDS and s not in seen:
            seen.add(s)
            valid.append(s)
    return ",".join(valid) if valid else ""


def _fallback(error_message):
    return {
        "_ai_error":          True,
        "is_research_poster": True,
        "title":              "Analysis Failed",
        "authors":            "",
        "conference":         "",
        "year":               "",
        "institution":        "",
        "subfields":          "",
        "search_query":       "",
        "github_query":       "",
    }


def _url_exists(url):
    try:
        return requests.head(
            url, headers=HEADERS, timeout=5, allow_redirects=True
        ).status_code == 200
    except Exception:
        return False


def _resolve_url(href, base_url):
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        p = urlparse(base_url)
        return f"{p.scheme}://{p.netloc}{href}"
    return base_url.rsplit("/", 1)[0] + "/" + href


def _is_blocked(url):
    try:
        return any(d in urlparse(url).netloc.lower() for d in BLOCKED_DOMAINS)
    except Exception:
        return False


def _encode_image_to_base64(image_path):
    ext = str(image_path).rsplit(".", 1)[-1].lower()
    mime = {"png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"



def extract_poster_info(image_path):
    if not API_KEY_CONFIGURED or _openai_client is None:
        return _fallback("OpenAI API not configured")
    try:
        data_url = _encode_image_to_base64(image_path)
        response = _openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": POSTER_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            }],
            max_tokens=1024,
            temperature=0.2,
        )
        text  = response.choices[0].message.content or ""
        clean = text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return _fallback("Invalid JSON from AI")
    except Exception as e:
        return _fallback(str(e))



def _search_semantic_scholar(query, limit=5):
    for attempt in range(2):
        try:
            resp = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "fields": "title,url,authors,externalIds,openAccessPdf,year,abstract",
                    "limit": limit,
                },
                headers=_ss_headers(),
                timeout=10,
            )
            if resp.status_code == 429 and attempt == 0:
                time.sleep(3)
                continue
            if resp.status_code != 200:
                return []
            results = []
            for paper in resp.json().get("data", []):
                ext = paper.get("externalIds") or {}
                arxiv_id = ext.get("ArXiv", "")
                if arxiv_id:
                    paper_url = f"https://arxiv.org/abs/{arxiv_id}"
                    pdf_url   = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                else:
                    paper_url = paper.get("url", "")
                    pdf_url   = (paper.get("openAccessPdf") or {}).get("url", "")
                authors = ", ".join(
                    a.get("name", "")
                    for a in (paper.get("authors") or [])
                    if a.get("name")
                )
                results.append({
                    "title":     paper.get("title", ""),
                    "paper_url": paper_url,
                    "pdf_url":   pdf_url,
                    "authors":   authors,
                    "arxiv_id":  arxiv_id,
                    "doi":       ext.get("DOI", ""),
                    "abstract":  paper.get("abstract", "") or "",
                    "year":      paper.get("year"),
                    "_blocked":  _is_blocked(paper_url),
                })
            return results
        except Exception as e:
            logger.warning("Semantic Scholar search failed: %s", e)
            return []
    return []


def _search_google_scholar(query, limit=5):
    try:
        soup = BeautifulSoup(
            requests.get(
                f"https://scholar.google.com/scholar?q={quote_plus(query)}",
                headers=HEADERS,
                timeout=10,
            ).text,
            "html.parser",
        )
        results = []
        for card in soup.select(".gs_r.gs_or")[:limit]:
            ri = card.select_one(".gs_ri")
            if not ri:
                continue
            a = ri.select_one(".gs_rt a")
            if not a:
                continue
            href = a.get("href", "")
            if not href:
                continue
            pdf_a = card.select_one(".gs_or_ggsm a")
            results.append({
                "title":     a.text,
                "paper_url": href,
                "pdf_url":   pdf_a.get("href", "") if pdf_a else "",
                "authors":   "",
                "arxiv_id":  "",
                "doi":       "",
                "_blocked":  _is_blocked(href),
            })
        return results
    except Exception:
        return []


def _title_similarity(query, candidate_title):
    if not query or not candidate_title:
        return 0.0
    q_words = set(re.findall(r"\w{3,}", query.lower()))
    c_words = set(re.findall(r"\w{3,}", candidate_title.lower()))
    if not q_words or not c_words:
        return 0.0
    overlap = len(q_words & c_words)
    return max(overlap / len(q_words), overlap / len(c_words))


def search_paper(query):
    if not query or not query.strip():
        return None
    blocked_fallback = None
    for source_fn in (_search_semantic_scholar, _search_google_scholar):
        for r in source_fn(query):
            if _title_similarity(query, r.get("title", "")) < 0.55:
                logger.debug("Skipping low-match result: %s", r.get("title", ""))
                continue
            if not r.get("_blocked"):
                return r
            if not blocked_fallback:
                blocked_fallback = r
    return blocked_fallback



def _is_valid_pdf_url(url):
    if not url:
        return False
    if url.lower().endswith(".pdf"):
        return True
    if "doi.org/" in url:
        return False
    try:
        resp = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
        ct = resp.headers.get("Content-Type", "").lower()
        if resp.status_code == 200 and "pdf" in ct:
            return True
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True, stream=True)
        ct = resp.headers.get("Content-Type", "").lower()
        resp.close()
        return resp.status_code == 200 and "pdf" in ct
    except Exception:
        return False


def _find_pdf_url(soup, base_url):
    strategies = [
        lambda s: s.find("meta", {"name": "citation_pdf_url"}),
        lambda s: s.find("a", href=re.compile(r"\.pdf($|\?)", re.I)),
        lambda s: s.find("a", href=re.compile(r"arxiv\.org/pdf/", re.I)),
        lambda s: s.find("a", string=re.compile(r"\bPDF\b|Download\s+PDF", re.I)),
        lambda s: s.find("a", href=re.compile(r"stamp\.jsp", re.I)),
        lambda s: s.find("iframe", src=re.compile(r"\.pdf", re.I)),
    ]
    for strategy in strategies:
        el = strategy(soup)
        if not el:
            continue
        if el.name == "meta":
            href = el.get("content", "")
        elif el.name == "iframe":
            href = el.get("src", "")
        else:
            href = el.get("href", "")
        if href:
            return _resolve_url(href, base_url)
    return ""


def _find_pdf_via_arxiv(title):
    if not title:
        return ""
    try:
        resp = requests.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f'ti:"{title}"', "max_results": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            return ""
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            for link in entry.findall("atom:link", ns):
                if link.get("type") == "application/pdf" or link.get("title") == "pdf":
                    return link.get("href", "").replace("http://", "https://")
    except Exception as e:
        logger.debug("arXiv title search failed: %s", e)
    return ""




def _get_pdf_from_stamp(stamp_url):
    try:
        resp = requests.get(stamp_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""
        soup   = BeautifulSoup(resp.text, "html.parser")
        iframe = soup.find("iframe")
        if iframe and iframe.get("src", ""):
            src = iframe["src"]
            if not src.startswith("http"):
                src = f"https://ieeexplore.ieee.org{src}"
            return src
    except Exception:
        pass
    return ""


def _get_ieee_pdf(doi):
    try:
        resp = requests.get(
            f"https://doi.org/{doi}", headers=HEADERS, timeout=15, allow_redirects=True,
        )
        if resp.status_code != 200:
            return ""
        m = re.search(r"/document/(\d+)", resp.url)
        if not m:
            return ""
        return _get_pdf_from_stamp(
            f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={m.group(1)}"
        )
    except Exception as e:
        logger.debug("IEEE PDF extraction failed for DOI %s: %s", doi, e)
    return ""


def _get_pdf_from_page(page_url):
    if not page_url:
        return ""
    if page_url.lower().endswith(".pdf"):
        return page_url
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        pdf  = _find_pdf_url(soup, resp.url)
        if pdf and _is_valid_pdf_url(pdf):
            return pdf
        if pdf and "stamp.jsp" in pdf:
            return _get_pdf_from_stamp(pdf)
        return pdf or ""
    except Exception as e:
        logger.debug("Page scrape failed for %s: %s", page_url, e)
    return ""


def _get_pdf_from_doi(doi):
    if not doi:
        return ""
    if re.match(r"^10\.1109/", doi):
        pdf = _get_ieee_pdf(doi)
        if pdf:
            return pdf
    if re.match(r"^10\.1007/", doi):
        url = f"https://link.springer.com/content/pdf/{doi}.pdf"
        if _is_valid_pdf_url(url):
            return url
    if re.match(r"^10\.1145/", doi):
        url = f"https://dl.acm.org/doi/pdf/{doi}"
        if _is_valid_pdf_url(url):
            return url
    try:
        resp = requests.get(
            f"https://doi.org/{doi}", headers=HEADERS, timeout=15, allow_redirects=True,
        )
        if resp.status_code == 200:
            pdf = _find_pdf_url(BeautifulSoup(resp.text, "html.parser"), resp.url)
            if pdf:
                return pdf
    except Exception:
        pass
    return ""


def _find_pdf_via_google_scholar(title):
    if not title:
        return ""
    try:
        for result in _search_google_scholar(title, limit=3):
            if _title_similarity(title, result.get("title", "")) < 0.55:
                continue
            pdf = result.get("pdf_url", "")
            if pdf and _is_valid_pdf_url(pdf):
                return pdf
    except Exception as e:
        logger.debug("Google Scholar PDF search failed: %s", e)
    return ""


def _find_real_pdf(pdf_url_hint="", paper_link="", doi="", title=""):
    if pdf_url_hint and _is_valid_pdf_url(pdf_url_hint):
        return pdf_url_hint
    if paper_link:
        pdf = _get_pdf_from_page(paper_link)
        if pdf:
            return pdf
    if doi:
        pdf = _get_pdf_from_doi(doi)
        if pdf:
            return pdf
    if title:
        pdf = _find_pdf_via_google_scholar(title)
        if pdf:
            return pdf
        pdf = _find_pdf_via_arxiv(title)
        if pdf:
            return pdf
    return ""



def _extract_github_from_annotations(reader):
    urls = []
    for page in reader.pages:
        try:
            annots = page.get("/Annots")
            if not annots:
                continue
            if hasattr(annots, "get_object"):
                annots = annots.get_object()
            for annot in annots:
                annot_obj = annot.get_object() if hasattr(annot, "get_object") else annot
                if annot_obj.get("/Subtype") == "/Link":
                    action = annot_obj.get("/A")
                    if action:
                        if hasattr(action, "get_object"):
                            action = action.get_object()
                        uri = action.get("/URI", "")
                        if uri and "github.com" in uri.lower():
                            urls.append(uri)
        except Exception:
            continue
    return urls


def _normalize_github_urls_in_text(text):
    text = re.sub(r"(github\.com/[\w\-\.]+/)\s+([\w\-\.]+)", r"\1\2", text)
    text = re.sub(r"(github\.com/[\w\-\.]*)\s+([\w\-\.]*/)\s*(\S+)", r"\1\2\3", text)
    return text


def _fix_duplicated_name(url):
    parts = url.split("/")
    name  = parts[-1]
    owner = parts[-2]
    for length in range(4, len(name) // 2 + 1):
        prefix = name[:length]
        if name.startswith(prefix + prefix):
            fixed = f"https://github.com/{owner}/{prefix}"
            if _url_exists(fixed):
                return fixed
    return None


def _first_valid_github(text):
    repo_pat   = r'github\.com/([\w\-\.]+/[\w\-\.]+?)(?:/|\s|$|\)|\]|:|,|"|\'|\\|\.(?:\s|$))'
    org_pat    = r'github\.com/([\w\-\.]+?)(?:/|\s|$|\)|\]|:|,|"|\'|\\|\.(?:\s|$))'
    skip_parts = {"issues", "pulls", "wiki", "releases", "actions", "blob", "tree"}
    skip_orgs  = {
        "about", "features", "pricing", "enterprise", "settings",
        "login", "signup", "join", "explore", "topics", "trending",
        "collections", "sponsors", "marketplace", "security",
        "notifications", "new", "organizations", "orgs",
    }

    seen_repos = []
    for match in re.findall(repo_pat, text, re.I):
        repo  = match.strip().rstrip("/").rstrip(".")
        parts = repo.split("/")
        if len(parts) == 2 and parts[0] and parts[1].lower() not in skip_parts:
            url = f"https://github.com/{repo}"
            if url not in seen_repos:
                seen_repos.append(url)

    for url in seen_repos:
        if _url_exists(url):
            return url
        fixed = _fix_duplicated_name(url)
        if fixed:
            return fixed

    seen_orgs = []
    for match in re.findall(org_pat, text, re.I):
        name = match.strip().rstrip("/").rstrip(".")
        if not name or name.lower() in skip_orgs or "/" in name:
            continue
        url = f"https://github.com/{name}"
        if url not in seen_orgs and url not in seen_repos:
            seen_orgs.append(url)

    for url in seen_orgs:
        if _url_exists(url):
            return url

    return ""


MAX_PDF_BYTES = 50 * 1024 * 1024


def _download_pdf_safe(url, timeout=30):
    resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
    if resp.status_code != 200:
        resp.close()
        return None
    size = int(resp.headers.get("Content-Length", 0) or 0)
    if size > MAX_PDF_BYTES:
        resp.close()
        return None
    chunks, total = [], 0
    for chunk in resp.iter_content(65536):
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            resp.close()
            return None
        chunks.append(chunk)
    resp.close()
    return b"".join(chunks), resp


def _find_github_in_pdf(pdf_url):
    if not pdf_url:
        return ""
    try:
        result = _download_pdf_safe(pdf_url)
        if result is None:
            return ""
        content, resp = result
        if "html" in resp.headers.get("Content-Type", "").lower():
            real_pdf = _find_pdf_url(BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser"), resp.url)
            if not real_pdf:
                return ""
            result2 = _download_pdf_safe(real_pdf)
            if result2 is None:
                return ""
            content, resp = result2
        reader = pypdf.PdfReader(io.BytesIO(content))
        for url in _extract_github_from_annotations(reader):
            result = _first_valid_github(url)
            if result:
                return result
        text = "".join(page.extract_text() or "" for page in reader.pages)
        if not text:
            return ""
        return _first_valid_github(_normalize_github_urls_in_text(text))
    except Exception as e:
        logger.debug("PDF GitHub extraction error for %s: %s", pdf_url, e)
        return ""


def _search_github_api(title, github_query=""):
    if not github_query or not github_query.strip():
        return ""
    gq = github_query.strip().lower()
    if title:
        title_tokens = {w.lower() for w in re.findall(r"[\w\-]+", title)}
        if gq not in title_tokens:
            return ""
    else:
        return ""
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": gq, "sort": "best-match", "per_page": 5},
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code != 200:
            return ""
        for item in resp.json().get("items", []):
            repo_name = (item.get("name") or "").strip().lower()
            if repo_name == gq:
                return item.get("html_url", "")
    except Exception:
        pass
    return ""


def _scrape_page_for_github(url):
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        if "html" not in resp.headers.get("Content-Type", "").lower():
            return ""
        return _first_valid_github(resp.text)
    except Exception as e:
        logger.debug("Page GitHub scan error for %s: %s", url, e)
    return ""


def find_github_repo(pdf_url="", title="", github_query="", paper_url="", doi=""):
    pages_to_try = []
    if doi:
        pages_to_try.append(f"https://doi.org/{doi}")
    if paper_url:
        pages_to_try.append(paper_url)

    for page in pages_to_try:
        url = _scrape_page_for_github(page)
        if url:
            return url

    if pdf_url:
        url = _find_github_in_pdf(pdf_url)
        if url:
            return url

    if title or github_query:
        url = _search_github_api(title, github_query=github_query)
        if url:
            return url

    return ""



def _extract_authors_from_html(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            for item in (data if isinstance(data, list) else [data]):
                raw = item.get("author", [])
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
                if isinstance(raw, list):
                    names = [
                        a.get("name", "") if isinstance(a, dict) else str(a)
                        for a in raw
                    ]
                    names = [n for n in names if n.strip()]
                    if names:
                        return ", ".join(names)
        except Exception:
            continue

    tags = soup.find_all(
        "meta",
        attrs={"name": re.compile(r"^(author|citation_author|dc\.creator)$", re.I)},
    )
    if tags:
        names = [t["content"].strip() for t in tags if t.get("content", "").strip()]
        if names:
            return ", ".join(names)

    og = soup.find("meta", attrs={"property": re.compile(r"author", re.I)})
    if og and og.get("content", "").strip():
        return og["content"].strip()

    return ""


def _authors_from_arxiv(arxiv_id):
    try:
        resp = requests.get(
            f"http://export.arxiv.org/api/query?id_list={arxiv_id}", timeout=10,
        )
        if resp.status_code == 200:
            entry = BeautifulSoup(resp.text, "xml").find("entry")
            if entry:
                names = [
                    a.find("name").text.strip()
                    for a in entry.find_all("author")
                    if a.find("name")
                ]
                if names:
                    return ", ".join(names)
    except Exception:
        pass
    return ""


def _authors_from_semantic_scholar(identifier):
    try:
        resp = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/{quote_plus(identifier)}",
            params={"fields": "authors"},
            headers=_ss_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            names = [
                a["name"]
                for a in resp.json().get("authors", [])
                if a.get("name")
            ]
            if names:
                return ", ".join(names)
    except Exception:
        pass
    return ""


def fetch_authors(paper_url, title=""):
    if not paper_url and not title:
        return ""

    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", paper_url or "", re.I)
    if m:
        result = _authors_from_arxiv(m.group(1))
        if result:
            return result

    doi_m = re.search(r"(10\.\d{4,9}/[\-\._();/:A-Z0-9]+)", paper_url or "", re.I)
    if doi_m:
        result = _authors_from_semantic_scholar(f"DOI:{doi_m.group(1)}")
        if result:
            return result

    if paper_url:
        try:
            resp = requests.get(paper_url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                result = _extract_authors_from_html(soup)
                if result:
                    return result
                if not doi_m:
                    doi_in_page = re.search(
                        r"(10\.\d{4,9}/[\-\._();/:A-Z0-9]+)", resp.text, re.I,
                    )
                    if doi_in_page:
                        result = _authors_from_semantic_scholar(f"DOI:{doi_in_page.group(1)}")
                        if result:
                            return result
        except Exception:
            pass

    if title and title.strip():
        try:
            resp = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": title, "fields": "authors", "limit": 1},
                headers=_ss_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                papers = resp.json().get("data", [])
                if papers:
                    names = [a["name"] for a in papers[0].get("authors", []) if a.get("name")]
                    if names:
                        return ", ".join(names)
        except Exception:
            pass

    return ""



def _extract_text_from_pdf(pdf_url, max_pages=8):
    if not pdf_url:
        return ""
    try:
        result = _download_pdf_safe(pdf_url)
        if result is None:
            return ""
        content, resp = result
        if "html" in resp.headers.get("Content-Type", "").lower():
            return ""
        reader = pypdf.PdfReader(io.BytesIO(content))
        text   = "\n".join(page.extract_text() or "" for page in reader.pages[:max_pages])
        text   = re.sub(r"[ \t]+", " ", text)
        text   = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception as e:
        logger.debug("PDF text extraction failed for %s: %s", pdf_url, e)
        return ""


def _generate_description_from_pdf(pdf_url):
    if not API_KEY_CONFIGURED or _openai_client is None:
        return ""
    pdf_text = _extract_text_from_pdf(pdf_url)
    if not pdf_text or len(pdf_text) < 200:
        return ""
    try:
        response = _openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": DESCRIPTION_FROM_PDF_PROMPT},
                {"role": "user",   "content": pdf_text[:12000]},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("GPT description-from-PDF failed: %s", e)
        return ""


def _shorten_scraped_description(raw_text):
    if not raw_text or not raw_text.strip():
        return ""
    if len(raw_text.split()) <= 100:
        return raw_text
    if not API_KEY_CONFIGURED or _openai_client is None:
        return raw_text
    try:
        response = _openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": DESCRIPTION_FROM_SCRAPE_PROMPT},
                {"role": "user",   "content": raw_text[:6000]},
            ],
            max_tokens=250,
            temperature=0.3,
        )
        shortened = (response.choices[0].message.content or "").strip()
        return shortened if shortened else raw_text
    except Exception as e:
        logger.warning("GPT description-from-scrape failed: %s", e)
        return raw_text


def _scrape_raw_from_site(paper_url):
    if not paper_url:
        return ""
    try:
        resp = requests.get(paper_url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")

        bq = soup.find("blockquote", class_="abstract")
        if bq:
            text = re.sub(r"^Abstract:?\s*", "", bq.get_text(separator=" ").strip(), flags=re.I)
            if text:
                return text

        for css in (
            "#Abs1-content", "#Abs1 p", ".c-article-section__content",
            ".abstract-content", ".abstractSection", ".abstract",
            "#abstract", "[class*='abstract']", ".paper-abstract", ".article-abstract",
        ):
            el = soup.select_one(css)
            if el:
                text = re.sub(r"^Abstract:?\s*", "", el.get_text(separator=" ").strip(), flags=re.I)
                if len(text) > 80:
                    return text

        for sel, attr in (
            ({"name": "citation_abstract"}, "content"),
            ({"name": "DC.description"},    "content"),
            ({"name": "description"},        "content"),
            ({"property": "og:description"}, "content"),
        ):
            tag = soup.find("meta", sel)
            if tag and tag.get(attr, "").strip():
                return tag[attr].strip()

    except Exception as e:
        logger.debug("Site description scrape error for %s: %s", paper_url, e)
    return ""


def _scrape_description_from_site(paper_url):
    return _shorten_scraped_description(_scrape_raw_from_site(paper_url))



def _generate_description_from_poster(image_path):
    if not API_KEY_CONFIGURED or _openai_client is None:
        return ""
    try:
        from bot_engine.prompts import DESCRIPTION_FROM_POSTER_PROMPT
        data_url = _encode_image_to_base64(image_path)
        response = _openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": DESCRIPTION_FROM_POSTER_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            }],
            max_tokens=300,
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("Poster image summary fallback failed: %s", e)
        return ""


def match_user_tags_to_subfields(user_tags, existing_subfields_csv=""):
    if not user_tags or not user_tags.strip():
        return existing_subfields_csv
    if not API_KEY_CONFIGURED or _openai_client is None:
        return existing_subfields_csv

    existing_slugs = [s.strip() for s in existing_subfields_csv.split(",") if s.strip()]
    all_valid      = sorted(VALID_SUBFIELDS - set(existing_slugs))

    try:
        response = _openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": build_tag_match_prompt(user_tags, all_valid)}],
            max_tokens=60,
            temperature=0,
        )
        raw       = (response.choices[0].message.content or "").strip()
        new_slugs = [s for s in _parse_subfields(raw).split(",") if s.strip()]
        combined  = existing_slugs + [s for s in new_slugs if s not in existing_slugs]
        return ",".join(combined[:6])
    except Exception as e:
        logger.warning("Tag-matching GPT call failed: %s", e)
        return existing_subfields_csv


def generate_why_useful(summary="", user_notes="", user_tags=""):
    """Genera perché il paper è utile combinando summary AI + note + tag utente."""
    if not API_KEY_CONFIGURED or _openai_client is None:
        return ""

    parts = []
    if summary and summary.strip():
        parts.append(f"Abstract/summary:\n{summary.strip()}")
    if user_notes and user_notes.strip():
        parts.append(f"User notes:\n{user_notes.strip()}")
    if user_tags and user_tags.strip():
        parts.append(f"User tags:\n{user_tags.strip()}")

    if not parts:
        return ""

    try:
        response = _openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": WHY_USEFUL_PROMPT},
                {"role": "user",   "content": "\n\n".join(parts)},
            ],
            max_tokens=150,
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("GPT why-useful generation failed: %s", e)
        return ""



def _resolve_year(ai_year, paper_result, paper_link):
    """Resolve publication year from multiple sources."""

    if ai_year and str(ai_year).strip().isdigit():
        return int(str(ai_year).strip()[:4])

    if paper_result and paper_result.get("year"):
        return paper_result["year"]
    
    if paper_link:
        arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{2})\d{2}\.\d+', paper_link, re.I)
        if arxiv_match:
            return 2000 + int(arxiv_match.group(1))

    return ""


def analyze_and_enrich(image_path):
    info = extract_poster_info(image_path)

    if info.get("_ai_error"):
        return info

    if not info.get("is_research_poster"):
        logger.info("Image is not a research poster, skipping enrichment.")
        return {
            "is_research_poster": False,
            "title":       "",
            "authors":     "",
            "summary":     "",
            "subfields":   "",
            "paper_link":  "",
            "github_link": "",
            "publication_year": "",
            "notes":       "",
        }

    title        = info.get("title", "")
    search_query = info.get("search_query", "")

    paper_result = search_paper(search_query)
    if not paper_result and title and title != search_query:
        logger.debug("Retrying search with full title: %s", title)
        paper_result = search_paper(title)

    paper_link        = ""
    pdf_url_hint      = ""
    doi               = ""
    authors_from_api  = ""
    abstract_from_api = ""

    if paper_result:
        paper_link        = paper_result.get("paper_url", "")
        pdf_url_hint      = paper_result.get("pdf_url", "")
        doi               = paper_result.get("doi", "")
        authors_from_api  = paper_result.get("authors", "")
        abstract_from_api = paper_result.get("abstract", "")

    pdf_url = _find_real_pdf(
        pdf_url_hint=pdf_url_hint,
        paper_link=paper_link,
        doi=doi,
        title=title,
    )

    github_url = find_github_repo(
        pdf_url=pdf_url,
        title=title,
        github_query=info.get("github_query", ""),
        paper_url=paper_link,
        doi=doi,
    )

    authors_from_page = ""
    if paper_link and not authors_from_api:
        authors_from_page = fetch_authors(paper_link, title=title)
    authors_raw = authors_from_page or authors_from_api or info.get("authors", "")
    # Deduplicate authors (GPT may extract the same name twice from poster)
    seen = set()
    unique = []
    for a in (x.strip() for x in authors_raw.split(",") if x.strip()):
        key = a.lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    authors = ", ".join(unique)

    description = ""
    for _key, fn in (
        ("pdf",      lambda: _generate_description_from_pdf(pdf_url) if pdf_url else ""),
        ("pdf_hint", lambda: _generate_description_from_pdf(pdf_url_hint) if (pdf_url_hint and pdf_url_hint != pdf_url) else ""),
        ("site",     lambda: _scrape_description_from_site(paper_link) if paper_link else ""),
        ("doi",      lambda: _scrape_description_from_site(f"https://doi.org/{doi}") if doi else ""),
        ("api",      lambda: abstract_from_api or ""),
        ("poster",   lambda: _generate_description_from_poster(image_path)),
    ):
        if not description:
            description = fn() or ""

    return {
        "is_research_poster": info.get("is_research_poster", True),
        "title":       info.get("title", "Untitled"),
        "authors":     authors,
        "summary":     description,
        "subfields":   _parse_subfields(info.get("subfields", [])),
        "paper_link":  paper_link,
        "github_link": github_url,
        "publication_year": _resolve_year(info.get("year", ""), paper_result, paper_link),
        "notes": (
            f"Auto-extracted by AI. "
            f"Conference: {info.get('conference', 'N/A')}, "
            f"Institution: {info.get('institution', 'N/A')}"
        ),
    }
