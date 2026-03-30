import csv
import json
import logging
import os
import re

import requests
from celery import current_app as celery_app
from celery.result import AsyncResult
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .forms import PosterUploadForm, PosterEditForm
from .models import ResearchPoster, ActivityLog, Favorite
from .utils_ai import analyze_and_enrich, match_user_tags_to_subfields, generate_why_useful
from .tasks import process_poster_task, process_bot_poster_task, download_and_handle_media_task

logger = logging.getLogger(__name__)

BOT_TOKEN             = settings.BOT_TOKEN
WHATSAPP_TOKEN        = settings.WHATSAPP_TOKEN
WHATSAPP_PHONE_ID     = settings.WHATSAPP_PHONE_ID
WHATSAPP_VERIFY_TOKEN = settings.WHATSAPP_VERIFY_TOKEN

BOT_STATE_TTL     = 7200
WELCOMED_TTL      = 86400
BOT_RATELIMIT_TTL = 300


def _get_pending(platform, recipient):
    return cache.get(f"bot:{platform}:{recipient}")

def _set_pending(platform, recipient, data):
    cache.set(f"bot:{platform}:{recipient}", data, timeout=BOT_STATE_TTL)

def _del_pending(platform, recipient):
    cache.delete(f"bot:{platform}:{recipient}")

def _is_welcomed(platform, recipient):
    return bool(cache.get(f"bot:welcomed:{platform}:{recipient}"))

def _set_welcomed(platform, recipient):
    cache.set(f"bot:welcomed:{platform}:{recipient}", 1, timeout=WELCOMED_TTL)

def _check_ratelimit(platform, recipient):
    return bool(cache.get(f"bot:ratelimit:{platform}:{recipient}"))

def _set_ratelimit(platform, recipient):
    cache.set(f"bot:ratelimit:{platform}:{recipient}", 1, timeout=BOT_RATELIMIT_TTL)

def _clear_ratelimit(platform, recipient):
    cache.delete(f"bot:ratelimit:{platform}:{recipient}")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("dashboard")
    return render(request, "login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("login")


def download_telegram_file(file_id):
    try:
        info = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}",
            timeout=10,
        ).json()
        file_path = info["result"]["file_path"]
        return requests.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}",
            timeout=10,
        ).content
    except Exception as e:
        logger.warning("Telegram download failed for %s: %s", file_id, e)
        return None


def download_whatsapp_media(media_id):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        info = requests.get(
            f"https://graph.facebook.com/v21.0/{media_id}",
            headers=headers,
            timeout=10,
        ).json()
        media_url = info.get("url")
        if not media_url:
            return None
        return requests.get(media_url, headers=headers, timeout=10).content
    except Exception as e:
        logger.warning("WhatsApp download failed for %s: %s", media_id, e)
        return None


def get_file_extension(filename, mime_type=None):
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return {
        "image/jpeg": "jpg",
        "image/png":  "png",
        "image/gif":  "gif",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }.get(mime_type, "jpg")


MESSAGE_TEMPLATES = {
    "welcome": {
        "telegram": (
            "<b>Welcome to Research Paper Assistant</b>\n\n"
            "Send me a photo of a research poster and I will:\n"
            "  • Extract title, authors and metadata\n"
            "  • Find the published paper link\n"
            "  • Search for the GitHub repository\n"
            "  • Generate a summary with GPT-4o\n\n"
            "📎 <b>Quick tip:</b> Add notes and tags in the caption:\n"
            "<code>note: interesting method  tag: mri, segmentation</code>\n\n"
            "Type /help for all commands and tips."
        ),
        "whatsapp": (
            "*Welcome to Research Paper Assistant*\n\n"
            "Send me a photo of a research poster and I will:\n"
            "  • Extract title, authors and metadata\n"
            "  • Find the published paper link\n"
            "  • Search for the GitHub repository\n"
            "  • Generate a summary\n\n"
            "📎 *Quick tip:* Add notes and tags in the caption:\n"
            "`note: interesting method  tag: mri, segmentation`\n\n"
            "Type *help* for all commands and tips."
        ),
    },
    "help": {
        "telegram": (
            "<b>📖 Research Paper Assistant</b>\n\n"

            "<b>How to upload:</b>\n"
            "Send a photo or document of a research poster.\n"
            "The AI will extract metadata, find the paper link, "
            "and search for a GitHub repo.\n\n"

            "<b>📷 Tips for best results:</b>\n"
            "  • Use high-res images with readable text\n"
            "  • Include the full poster (title + authors + abstract)\n"
            "  • Avoid blurry or rotated photos\n"
            "  • JPG/PNG work best\n\n"

            "<b>📎 Add info via caption:</b>\n"
            "<code>note: your text  tag: deep learning, mri</code>\n\n"

            "<b>🔍 Search your collection:</b>\n"
            "  /search &lt;keyword&gt;\n"
            "Searches title, authors, summary, tags, subfields and category.\n\n"
            "<b>Year filter:</b>\n"
            "  /search transformer year:2024\n"
            "  /search segmentation year:2020-2024\n\n"

            "<b>All commands:</b>\n"
            "/start — Welcome message\n"
            "/help — This help page\n"
            "/dashboard — Open your collection\n"
            "/search &lt;keyword&gt; — Search papers"
        ),
        "whatsapp": (
            "*📖 Research Paper Assistant*\n\n"

            "*How to upload:*\n"
            "Send a photo or document of a research poster.\n"
            "The AI will extract metadata, find the paper link, "
            "and search for a GitHub repo.\n\n"

            "*📷 Tips for best results:*\n"
            "  • Use high-res images with readable text\n"
            "  • Include the full poster (title + authors + abstract)\n"
            "  • Avoid blurry or rotated photos\n"
            "  • JPG/PNG work best\n\n"

            "*📎 Add info via caption:*\n"
            "`note: your text  tag: deep learning, mri`\n\n"

            "*🔍 Search your collection:*\n"
            "  search <keyword>\n"
            "Searches title, authors, summary, tags, subfields and category.\n\n"
            "*Year filter:*\n"
            "  search transformer year:2024\n"
            "  search segmentation year:2020-2024\n\n"

            "*All commands:*\n"
            "*help* — This help page\n"
            "*dashboard* — Open your collection\n"
            "*search <keyword>* — Search papers"
        ),
    },
    "no_text": {
        "telegram": (
            "⚠️ <b>No research content detected</b>\n\n"
            "The image doesn't appear to contain a research poster.\n\n"
            "<b>Make sure:</b>\n"
            "  • The full poster is visible (title, authors, abstract)\n"
            "  • Text is sharp and readable\n"
            "  • The image is not rotated or cropped"
        ),
        "whatsapp": (
            "⚠️ *No research content detected*\n\n"
            "The image doesn't appear to contain a research poster.\n\n"
            "*Make sure:*\n"
            "  • The full poster is visible (title, authors, abstract)\n"
            "  • Text is sharp and readable\n"
            "  • The image is not rotated or cropped"
        ),
    },
    "analysis_failed": {
        "telegram": (
            "❌ <b>Analysis failed</b>. Check the internet connection.\n\n"
            "The image was saved to your collection.\n"
            "Press 🔄 Retry below when connectivity is restored."
        ),
        "whatsapp": (
            "❌ *Analysis failed*. Check the internet connection.\n\n"
            "The image was saved to your collection.\n"
            "Press 🔄 Retry below when connectivity is restored."
        ),
    },
    "fallback": {
        "telegram": (
            "Send me a photo or document of a research poster.\n"
            "Type /help for commands and upload tips."
        ),
        "whatsapp": (
            "Send me a photo or document of a research poster.\n"
            "Type *help* for commands and upload tips."
        ),
    },
    "download_error": {
        "telegram": "❌ Error downloading file.",
        "whatsapp": "❌ Error downloading file.",
    },
    "ratelimit": {
        "telegram": "⏳ <b>Analysis already in progress.</b>\nPlease wait for the current poster to finish before sending a new one.",
        "whatsapp": "⏳ *Analysis already in progress.*\nPlease wait for the current poster to finish before sending a new one.",
    },
    "analyzing": {
        "telegram": "⏳ <i>Analyzing your poster...</i> This may take a minute.",
        "whatsapp": "⏳ _Analyzing your poster..._ This may take a minute.",
    },
    "duplicate": {
        "telegram": (
            "⚠️ <b>Duplicate detected.</b>\n\n"
            "A paper titled <b>{title}</b> already exists in your collection.\n"
            "{paper_link_line}"
            "The uploaded file has been discarded."
        ),
        "whatsapp": (
            "⚠️ *Duplicate detected.*\n\n"
            "A paper titled *{title}* already exists in your collection.\n"
            "{paper_link_line}"
            "The uploaded file has been discarded."
        ),
    },
    "link_confirmation": {
        "telegram": (
            "🔗 <b>Retrieved paper link:</b>\n"
            "<code>{link}</code>\n\n"
            "Is this link correct?"
        ),
        "whatsapp": (
            "🔗 *Retrieved paper link:*\n"
            "{link}\n\n"
            "Is this link correct?"
        ),
    },
    "link_confirmed": {
        "telegram": "✅ <b>Link confirmed.</b> Paper saved to your collection.",
        "whatsapp": "✅ *Link confirmed.* Paper saved to your collection.",
    },
    "ask_url": {
        "telegram": "Please send the correct paper URL (starting with http...):",
        "whatsapp": "Please send the correct paper URL (starting with http...):",
    },
    "link_updated": {
        "telegram": "✅ <b>Link updated.</b>\n<i>{url}</i>\nPaper record has been saved.",
        "whatsapp": "✅ *Link updated.*\n_{url}_\nPaper record has been saved.",
    },
    "bad_url": {
        "telegram": "⚠️ Invalid URL format. Please send the full link starting with http:",
        "whatsapp": "⚠️ Invalid URL format. Please send the full link starting with http:",
    },
    "paper_not_found": {
        "telegram": "❌ <b>Paper not found.</b>",
        "whatsapp": "❌ *Paper not found.*",
    },
    "not_failed_state": {
        "telegram": "⚠️ <b>This paper is not in a failed state.</b>",
        "whatsapp": "⚠️ *This paper is not in a failed state.*",
    },
    "ask_add_info": {
        "telegram": "🖼️ <b>Image received.</b>\n\nWould you like to add <b>notes and tags</b> before analysis?",
        "whatsapp": "🖼️ *Image received.*\n\nWould you like to add *notes and tags* before analysis?",
    },
    "ask_notes_tags": {
        "telegram": (
            "📝 Please write your <b>notes and tags</b> in a single message.\n\n"
            "Recommended format:\n"
            "<code>note: your text  tag: deep learning, mri</code>\n\n"
            "Or write freely. The system will process the context."
        ),
        "whatsapp": (
            "📝 Please write your *notes and tags* in a single message.\n\n"
            "Recommended format:\n"
            "`note: your text  tag: deep learning, mri`\n\n"
            "Or write freely. The system will process the context."
        ),
    },
    "unrecognized_ask_info": {
        "telegram": "⚠️ Command not recognized. Would you like to add notes and tags?",
        "whatsapp": "⚠️ Command not recognized. Would you like to add notes and tags?",
    },
    "reply_1_or_2": {
        "telegram": "⚠️ Please reply <b>1</b> (yes) or <b>2</b> (no).",
        "whatsapp": "⚠️ Please reply *1* (yes) or *2* (no).",
    },
    "search_usage": {
        "telegram": (
            "🔍 <b>Search your collection</b>\n\n"
            "<b>Usage:</b> /search &lt;keyword&gt;\n\n"
            "Matches title, authors, summary, tags, subfields and category.\n\n"
            "<b>Examples:</b>\n"
            "  /search transformer\n"
            "  /search brain tumor\n"
            "  /search computer vision year:2024\n"
            "  /search segmentation year:2020-2024"
        ),
        "whatsapp": (
            "🔍 *Search your collection*\n\n"
            "*Usage:* search <keyword>\n\n"
            "Matches title, authors, summary, tags, subfields and category.\n\n"
            "*Examples:*\n"
            "  search transformer\n"
            "  search brain tumor\n"
            "  search computer vision year:2024\n"
            "  search segmentation year:2020-2024"
        ),
    },
    "search_no_results": {
        "telegram": "No papers found for '{query}'.",
        "whatsapp": "No papers found for '{query}'.",
    },
}


def _fmt(platform):
    if platform == "telegram":
        return (
            lambda t: f"<b>{t}</b>",
            lambda t: f"<i>{t}</i>",
            lambda text, url: f"<a href='{url}'>{text}</a>",
        )
    return (
        lambda t: f"*{t}*",
        lambda t: f"_{t}_",
        lambda text, url: url,
    )


def _truncate(text, max_len):
    return (text[:max_len] + "...") if len(text) > max_len else text


def send_message(platform, recipient, text):
    try:
        if platform == "telegram":
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": recipient, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        elif platform == "whatsapp":
            requests.post(
                f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages",
                headers={
                    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "text",
                    "text": {"body": text},
                },
                timeout=5,
            )
    except Exception as e:
        logger.warning("Failed to send %s message to %s: %s", platform, recipient, e)


def send_telegram_buttons(chat_id, text, buttons):
    keyboard = {"inline_keyboard": [[btn] for btn in buttons]}
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
            timeout=5,
        )
    except Exception as e:
        logger.warning("Failed to send Telegram buttons to %s: %s", chat_id, e)


def send_confirmation_buttons(platform, recipient, link):
    text = MESSAGE_TEMPLATES["link_confirmation"][platform].replace("{link}", link)
    try:
        if platform == "telegram":
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": recipient,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [[
                            {"text": "Yes, correct", "callback_data": "link_yes"},
                            {"text": "No, wrong",    "callback_data": "link_no"},
                        ]]
                    },
                },
                timeout=5,
            )
        elif platform == "whatsapp":
            requests.post(
                f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages",
                headers={
                    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": text},
                        "action": {
                            "buttons": [
                                {"type": "reply", "reply": {"id": "link_yes", "title": "Yes, correct"}},
                                {"type": "reply", "reply": {"id": "link_no",  "title": "No, wrong"}},
                            ]
                        },
                    },
                },
                timeout=5,
            )
    except Exception as e:
        logger.warning("Failed to send confirmation buttons to %s: %s", recipient, e)


def answer_telegram_callback(callback_query_id):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
            timeout=5,
        )
    except Exception as e:
        logger.warning("Failed to answer callback query %s: %s", callback_query_id, e)


def _is_empty_analysis(enriched_data):
    if not enriched_data:
        return True
    title       = (enriched_data.get("title") or "").strip().lower()
    description = (enriched_data.get("summary") or "").strip()
    authors     = (enriched_data.get("authors") or "").strip()
    if title not in {"", "untitled", "ai analysis failed", "analysis failed"}:
        return False
    return not description and not authors


def process_uploaded_poster(
    image_content,
    filename,
    source="web",
    existing_poster=None,
    user_notes=None,
    user_tags=None,
    activity_user=None,
):
    try:
        poster = existing_poster or ResearchPoster()

        if image_content and not existing_poster:
            poster.image.save(filename, ContentFile(image_content))

        if activity_user and not poster.uploaded_by_id:
            poster.uploaded_by = activity_user

        try:
            poster.ensure_image_sha256(save=bool(poster.pk))
            if poster.image_sha256:
                hash_dup = ResearchPoster.find_existing_by_hash(
                    poster.image_sha256, exclude_id=poster.pk
                )
                if hash_dup:
                    logger.info(
                        "Duplicate detected by image hash: new=%s existing=%s",
                        poster.pk, hash_dup.pk,
                    )
                    if image_content and not existing_poster:
                        poster.image.delete(save=False)
                        if poster.pk:
                            poster.delete()
                    return hash_dup, None, "duplicate"
        except Exception as e:
            logger.warning("Image hash check failed (continuing): %s", e)

        enriched_data = analyze_and_enrich(poster.image.path)

        if enriched_data.get("_ai_error"):
            if poster.title in ("Pending analysis…", ""):
                poster.title = "Analysis Failed"
            poster.analysis_status = 'failed'
            if poster.pk:
                poster.save(update_fields=["title", "analysis_status", "uploaded_by", "updated_at"])
            else:
                poster.save()
            return poster, None, "analysis_failed"

        if _is_empty_analysis(enriched_data):
            if image_content and not existing_poster:
                poster.image.delete(save=False)
                if poster.pk:
                    poster.delete()
            return None, None, "no_text"

        extracted_title = enriched_data.get("title", "").strip()
        if extracted_title and extracted_title.lower() not in {"", "untitled"}:
            norm_title = " ".join(extracted_title.lower().split())
            exclude_pk = poster.pk if poster.pk else None
            existing   = ResearchPoster.objects.filter(
                title__iexact=extracted_title
            ).exclude(pk=exclude_pk).first()

            if not existing:
                words = [w for w in re.findall(r"[a-zA-Z]{4,}", norm_title)]
                if len(words) >= 3:
                    q = Q()
                    for w in words[:6]:
                        q |= Q(title__icontains=w)
                    candidates = ResearchPoster.objects.filter(q).exclude(pk=exclude_pk)
                    for c in candidates:
                        c_norm  = " ".join(c.title.lower().split())
                        c_words = set(re.findall(r"[a-zA-Z]{4,}", c_norm))
                        t_words = set(words)
                        overlap = len(c_words & t_words)
                        total   = max(len(c_words), len(t_words), 1)
                        if overlap / total >= 0.8:
                            existing = c
                            break

            if existing:
                if image_content and not existing_poster:
                    poster.image.delete(save=False)
                    if poster.pk:
                        poster.delete()
                return existing, enriched_data, "duplicate"

        for field, (key, default) in {
            "title":       ("title", "Untitled"),
            "authors":     ("authors", ""),
            "summary":     ("summary", ""),
            "subfields":   ("subfields", ""),
            "paper_link":  ("paper_link", ""),
            "github_link": ("github_link", ""),
        }.items():
            setattr(poster, field, enriched_data.get(key, default))

        raw_year = enriched_data.get("publication_year", "")
        if raw_year:
            try:
                poster.publication_year = int(str(raw_year).strip()[:4])
            except (ValueError, TypeError):
                pass

        poster.derive_category_from_subfields()

        if user_tags and user_tags.strip():
            merged = match_user_tags_to_subfields(user_tags, poster.subfields)
            if merged:
                poster.subfields = merged
                poster.derive_category_from_subfields()

            slug_to_label = {s: lbl for s, lbl in ResearchPoster.SUBFIELD_CHOICES}
            absorbed = (
                {slug_to_label.get(s, s).lower() for s in poster.subfields_list}
                | {s.lower() for s in poster.subfields_list}
            )
            seen = set()
            leftover = []
            for t in user_tags.split(","):
                t = t.strip()
                key = t.lower()
                if t and key not in absorbed and key not in seen:
                    seen.add(key)
                    leftover.append(t)
            poster.tags = ", ".join(leftover)
        elif not poster.tags:
            poster.tags = enriched_data.get("tags", "")

        if user_notes and user_notes.strip():
            poster.notes = user_notes.strip()
        else:
            poster.notes = enriched_data.get("notes", f"Auto-extracted via {source}")

        poster.why_useful = generate_why_useful(
            summary=poster.summary,
            user_notes=user_notes.strip() if user_notes and user_notes.strip() else "",
            user_tags=user_tags.strip() if user_tags and user_tags.strip() else "",
        )

        poster.validation_status = "pending"
        poster.analysis_status   = 'ok'
        poster.save()

        ActivityLog.objects.create(
            user=activity_user,
            poster=poster,
            action="created",
            poster_title=poster.title,
            details=f"Uploaded via {source} + AI analysis",
        )
        return poster, enriched_data, None

    except Exception as e:
        logger.error("process_uploaded_poster failed: %s", e)
        return None, None, str(e)


def _build_links_section(poster, platform):
    bold, italic, link_fn = _fmt(platform)
    paper  = link_fn("View Paper", poster.paper_link) if poster.paper_link else italic("Not found")
    github = link_fn("View Code", poster.github_link) if poster.github_link else italic("Not found")
    return (
        f"{bold('Resources')}\n"
        f"   Link: {paper}\n"
        f"   GitHub: {github}"
    )


def _send_analysis_result(platform, recipient, poster):
    bold, italic, _ = _fmt(platform)
    title_max  = 80 if platform == "telegram" else 60
    author_max = 50 if platform == "telegram" else 40

    msg_parts = [
        f"{bold('✅ Analysis Complete')}\n",
        f"{bold('Title:')} {_truncate(poster.title, title_max)}",
        f"{bold('Authors:')} {_truncate(poster.authors, author_max)}",
        f"{bold('Category:')} {poster.get_category_display()}",
    ]

    if poster.why_useful and poster.why_useful.strip():
        msg_parts.append(f"\n💡 {italic(poster.why_useful.strip())}")

    msg_parts.append(f"\n{_build_links_section(poster, platform)}")
    msg_parts.append(italic("Successfully added to your collection"))
    send_message(platform, recipient, "\n".join(msg_parts))

def _save_image_only(image_content, filename, uploaded_by=None, source='web'):
    poster               = ResearchPoster()
    poster.image.save(filename, ContentFile(image_content))
    poster.title         = "Pending analysis…"
    poster.authors       = ""
    poster.summary       = ""
    poster.uploaded_by   = uploaded_by
    poster.upload_source = source
    poster.save()
    return poster


def _extract_inline_notes_and_tags(caption):
    if not caption:
        return "", ""
    text = caption.strip()
    tag_pattern  = re.compile(
        r'(?:tags?|tga|tgs|tg)\s*[:\-]\s*(.+?)(?=\s+(?:note|notes|nte|nota)\s*[:\-]|$)',
        re.IGNORECASE,
    )
    note_pattern = re.compile(
        r'(?:notes?|nte|nota)\s*[:\-]\s*(.+?)(?=\s+(?:tags?|tga|tgs|tg)\s*[:\-]|$)',
        re.IGNORECASE,
    )
    tag_match  = tag_pattern.search(text)
    note_match = note_pattern.search(text)
    tags  = tag_match.group(1).strip()  if tag_match  else ""
    notes = note_match.group(1).strip() if note_match else ""
    if not tag_match and not note_match:
        notes = text
        tags  = ""
    return notes[:500], tags[:200]


def _dispatch_bot_analysis(platform, recipient, poster_id, notes, tags):
    ResearchPoster.objects.filter(pk=poster_id).update(analysis_status='processing')
    _set_pending(platform, recipient, {"poster_id": poster_id, "state": "processing"})
    _set_ratelimit(platform, recipient)

    if notes or tags:
        bold, italic, _ = _fmt(platform)
        confirm_parts = [f"📋 {bold('Got it!')}"]
        if notes:
            confirm_parts.append(f"   Notes: {italic(_truncate(notes, 80))}")
        if tags:
            confirm_parts.append(f"   Tags: {italic(tags)}")
        send_message(platform, recipient, "\n".join(confirm_parts))

    send_message(platform, recipient, MESSAGE_TEMPLATES["analyzing"][platform])
    task = process_bot_poster_task.delay(
        platform=platform,
        recipient=recipient,
        poster_id=poster_id,
        notes=notes,
        tags=tags,
    )
    cache.set(f"bot:task:{poster_id}", task.id, timeout=BOT_STATE_TTL)
    cache.set(f"bot:context:{poster_id}", {"platform": platform, "recipient": recipient}, timeout=BOT_STATE_TTL)


def _handle_bot_retry(platform, recipient, poster_id):
    poster = ResearchPoster.objects.filter(pk=poster_id).first()
    if not poster:
        send_message(platform, recipient, MESSAGE_TEMPLATES["paper_not_found"][platform])
        return
    if poster.analysis_status != 'failed':
        send_message(platform, recipient, MESSAGE_TEMPLATES["not_failed_state"][platform])
        return
    if _check_ratelimit(platform, recipient):
        send_message(platform, recipient, MESSAGE_TEMPLATES["ratelimit"][platform])
        return
    _dispatch_bot_analysis(platform, recipient, poster_id, notes=poster.notes, tags=poster.tags)


def _handle_media_upload(platform, recipient, media_content, filename, caption=None):
    if not media_content:
        send_message(platform, recipient, MESSAGE_TEMPLATES["download_error"][platform])
        return

    if _check_ratelimit(platform, recipient):
        send_message(platform, recipient, MESSAGE_TEMPLATES["ratelimit"][platform])
        return

    poster = _save_image_only(media_content, filename, source=platform)

    if caption and caption.strip():
        notes, tags = _extract_inline_notes_and_tags(caption)
        _dispatch_bot_analysis(platform, recipient, poster.pk, notes, tags)
        return

    _set_pending(platform, recipient, {"poster_id": poster.pk, "state": "awaiting_add_info"})

    text_msg = MESSAGE_TEMPLATES["ask_add_info"][platform]
    if platform == "telegram":
        send_telegram_buttons(
            recipient,
            text_msg,
            [
                {"text": "Yes, add info",   "callback_data": "add_info_yes"},
                {"text": "No, analyze now", "callback_data": "add_info_no"},
            ],
        )
    else:
        try:
            requests.post(
                f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages",
                headers={
                    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": text_msg},
                        "action": {
                            "buttons": [
                                {"type": "reply", "reply": {"id": "add_info_yes", "title": "Yes, add info"}},
                                {"type": "reply", "reply": {"id": "add_info_no",  "title": "No, analyze now"}},
                            ]
                        },
                    },
                },
                timeout=5,
            )
        except Exception as e:
            logger.warning("WhatsApp button send failed: %s", e)


def _handle_pending_validation_text(platform, recipient, text):
    pending = _get_pending(platform, recipient)
    if not pending:
        return False

    state      = pending["state"]
    poster     = ResearchPoster.objects.filter(pk=pending["poster_id"]).first()
    normalized = text.strip().lower()

    if state == "processing":
        return True

    if state == "awaiting_add_info":
        YES = {"1", "si", "sì", "yes", "y", "ok", "sure", "yep"}
        NO  = {"2", "no", "n", "nope", "nah"}

        if normalized in YES:
            _set_pending(platform, recipient, {**pending, "state": "awaiting_notes_and_tags"})
            send_message(platform, recipient, MESSAGE_TEMPLATES["ask_notes_tags"][platform])
            return True

        elif normalized in NO:
            _dispatch_bot_analysis(platform, recipient, pending["poster_id"], notes=None, tags=None)
            return True

        else:
            if platform == "telegram":
                send_telegram_buttons(
                    recipient,
                    MESSAGE_TEMPLATES["unrecognized_ask_info"][platform],
                    [
                        {"text": "Yes, add info",   "callback_data": "add_info_yes"},
                        {"text": "No, analyze now", "callback_data": "add_info_no"},
                    ],
                )
            else:
                send_message(platform, recipient, MESSAGE_TEMPLATES["reply_1_or_2"][platform])
            return True

    if state == "awaiting_notes_and_tags":
        notes, tags = _extract_inline_notes_and_tags(text)
        _dispatch_bot_analysis(platform, recipient, pending["poster_id"], notes=notes, tags=tags)
        return True

    if state == "awaiting_confirmation":
        YES = {"yes", "si", "sì", "ok", "correct", "y", "yep", "yeah", "sure", "1"}
        NO  = {"no", "n", "nope", "wrong", "incorrect", "bad", "nah", "2"}
        if normalized in YES:
            _del_pending(platform, recipient)
            send_message(platform, recipient, MESSAGE_TEMPLATES["link_confirmed"][platform])
        elif normalized in NO:
            _set_pending(platform, recipient, {**pending, "state": "awaiting_url"})
            send_message(platform, recipient, MESSAGE_TEMPLATES["ask_url"][platform])
        else:
            return False
        return True

    if state == "awaiting_url":
        url = text.strip()
        if url.startswith("http"):
            if poster:
                poster.paper_link = url
                poster.save(update_fields=["paper_link", "updated_at"])
                ActivityLog.objects.create(
                    user=None, poster=poster, action="updated",
                    poster_title=poster.title,
                    details="Paper link updated by user via bot validation",
                )
            _del_pending(platform, recipient)
            msg = MESSAGE_TEMPLATES["link_updated"][platform].replace("{url}", url)
            send_message(platform, recipient, msg)
        else:
            send_message(platform, recipient, MESSAGE_TEMPLATES["bad_url"][platform])
        return True

    return False


def _handle_pending_callback(platform, recipient, callback_data):
    if callback_data.startswith("retry_"):
        try:
            poster_id = int(callback_data.split("_", 1)[1])
            _handle_bot_retry(platform, recipient, poster_id)
        except (ValueError, IndexError):
            logger.warning("Invalid retry callback data: %s", callback_data)
        return

    pending = _get_pending(platform, recipient)
    if not pending:
        return

    state = pending.get("state")

    if state == "awaiting_add_info":
        if callback_data == "add_info_yes":
            _set_pending(platform, recipient, {**pending, "state": "awaiting_notes_and_tags"})
            send_message(platform, recipient, MESSAGE_TEMPLATES["ask_notes_tags"][platform])
        elif callback_data == "add_info_no":
            _dispatch_bot_analysis(platform, recipient, pending["poster_id"], notes=None, tags=None)

    elif state == "awaiting_confirmation":
        if callback_data == "link_yes":
            _del_pending(platform, recipient)
            send_message(platform, recipient, MESSAGE_TEMPLATES["link_confirmed"][platform])
        elif callback_data == "link_no":
            _set_pending(platform, recipient, {**pending, "state": "awaiting_url"})
            send_message(platform, recipient, MESSAGE_TEMPLATES["ask_url"][platform])


def _handle_dashboard_command(platform, recipient):
    bold, italic, link_fn = _fmt(platform)

    total    = ResearchPoster.objects.count()
    pending  = ResearchPoster.objects.filter(validation_status="pending").count()
    approved = ResearchPoster.objects.filter(validation_status="approved").count()
    rejected = ResearchPoster.objects.filter(validation_status="rejected").count()

    top_cats = (
        ResearchPoster.objects
        .exclude(category="other")
        .values("category")
        .annotate(n=Count("id"))
        .order_by("-n")[:3]
    )
    cat_labels = dict(ResearchPoster.CATEGORY_CHOICES)
    cat_lines = ", ".join(
        f"{cat_labels.get(c['category'], c['category'])} ({c['n']})"
        for c in top_cats
    ) if top_cats else "—"

    recent = ResearchPoster.objects.order_by("-created_at")[:5]

    msg_parts = [
        f"{bold('📊 Research Collection')}\n",
        f"Total: {bold(str(total))}  •  ✅ {approved}  •  ⏳ {pending}  •  ❌ {rejected}",
        f"Top categories: {cat_lines}",
    ]

    if recent:
        title_max = 35 if platform == "telegram" else 30
        msg_parts.append(f"\n{bold('Recent Papers')}")
        for i, p in enumerate(recent, 1):
            status_icon = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(p.validation_status, "•")
            paper  = link_fn("Paper", p.paper_link) if p.paper_link else "—"
            github = link_fn("Code", p.github_link)  if p.github_link else "—"
            msg_parts.append(f"{i}. {status_icon} {bold(_truncate(p.title, title_max))}")
            msg_parts.append(f"   {paper} • {github}")
    else:
        msg_parts.append(f"\n{italic('No papers in your collection yet.')}")

    send_message(platform, recipient, "\n".join(msg_parts))


def _handle_search_command(platform, recipient, query):
    if not query:
        send_message(platform, recipient, MESSAGE_TEMPLATES["search_usage"][platform])
        return

    import html as html_mod

    year_from = None
    year_to = None
    year_match = re.search(r'\byear:(\d{4})(?:-(\d{4}))?\b', query)
    if year_match:
        year_from = int(year_match.group(1))
        year_to = int(year_match.group(2)) if year_match.group(2) else year_from
        query = query[:year_match.start()].strip() + " " + query[year_match.end():].strip()
        query = query.strip()

    if not query and not year_from:
        send_message(platform, recipient, MESSAGE_TEMPLATES["search_usage"][platform])
        return

    safe_query = html_mod.escape(query) if platform == "telegram" else query

    qs = ResearchPoster.objects.exclude(validation_status="rejected")
    if query:
        q_filter = (
            Q(title__icontains=query) | Q(authors__icontains=query) |
            Q(summary__icontains=query) | Q(tags__icontains=query) |
            Q(subfields__icontains=query) | Q(category__icontains=query)
        )

    
        query_lower = query.lower()
        query_slug = query_lower.replace(" ", "_").replace("-", "_")
        if query_slug != query_lower:
            q_filter |= Q(subfields__icontains=query_slug) | Q(category__icontains=query_slug)

        for cat_slug, cat_label in ResearchPoster.CATEGORY_CHOICES:
            if query_lower in cat_label.lower():
                q_filter |= Q(category=cat_slug)
                
        for sf_slug, sf_label in ResearchPoster.SUBFIELD_CHOICES:
            if query_lower in sf_label.lower():
                q_filter |= Q(subfields__icontains=sf_slug)

        qs = qs.filter(q_filter)
    if year_from:
        qs = qs.filter(publication_year__gte=year_from)
    if year_to:
        qs = qs.filter(publication_year__lte=year_to)

    results = qs.order_by("-created_at")[:5]

    if not results:
        msg = MESSAGE_TEMPLATES["search_no_results"][platform].replace("{query}", safe_query)
        send_message(platform, recipient, msg)
        return

    bold, italic, link_fn = _fmt(platform)
    title_max = 50 if platform == "telegram" else 40
    lines = [f"🔍 {bold('Results for:')} {italic(safe_query)}  ({len(results)} found)\n"]
    for i, p in enumerate(results, 1):
        paper  = link_fn("Paper", p.paper_link) if p.paper_link else "—"
        github = link_fn("Code", p.github_link)  if p.github_link else "—"
        subfields = ", ".join(p.subfields_display[:3]) if p.subfields_display else ""

        year_str = f" ({p.publication_year})" if p.publication_year else ""
        lines.append(f"{i}. {bold(_truncate(p.title, title_max))}{year_str}")
        if subfields:
            lines.append(f"   {p.get_category_display()} · {subfields}")
        else:
            lines.append(f"   {p.get_category_display()}")
        lines.append(f"   {paper} • {github}")

        if p.why_useful and p.why_useful.strip():
            lines.append(f"   💡 {italic(_truncate(p.why_useful.strip(), 80))}")
        lines.append("")

    send_message(platform, recipient, "\n".join(lines).strip())


def _apply_filters(queryset, params, favorite_user=None):
    search = params.get("search", "")
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search) | Q(authors__icontains=search) |
            Q(summary__icontains=search) | Q(tags__icontains=search) |
            Q(subfields__icontains=search)
        )

    for param, field in (
        ("author",  "authors__icontains"),
        ("summary", "summary__icontains"),
    ):
        val = params.get(param, "").strip()
        if val:
            queryset = queryset.filter(**{field: val})

    date_from = params.get("date_from", "").strip()
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)

    date_to = params.get("date_to", "").strip()
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    year_from = params.get("year_from", "").strip()
    if year_from:
        try:
            queryset = queryset.filter(publication_year__gte=int(year_from))
        except (ValueError, TypeError):
            pass

    year_to = params.get("year_to", "").strip()
    if year_to:
        try:
            queryset = queryset.filter(publication_year__lte=int(year_to))
        except (ValueError, TypeError):
            pass

    status = params.get("status", "")
    if status:
        queryset = queryset.filter(validation_status=status)

    category = params.get("category", "")
    if category:
        queryset = queryset.filter(category=category)

    subfields_param = params.getlist("subfield") if hasattr(params, "getlist") else []
    if not subfields_param:
        sf_single = params.get("subfield", "")
        if sf_single:
            subfields_param = sf_single.split(",")
    for sf in subfields_param:
        sf = sf.strip()
        if sf:
            queryset = queryset.filter(subfields__icontains=sf)

    if params.get("has_github", ""):
        queryset = queryset.exclude(github_link="").exclude(github_link__isnull=True)
    if params.get("has_paper", ""):
        queryset = queryset.exclude(paper_link="").exclude(paper_link__isnull=True)

    if params.get("favorites", ""):
        if favorite_user and favorite_user.is_authenticated:
            queryset = queryset.filter(favorites__user=favorite_user).distinct()
        else:
            queryset = queryset.none()

    return queryset


def _get_stats(user):
    stats = ResearchPoster.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(validation_status="pending")),
        approved=Count("id", filter=Q(validation_status="approved")),
        rejected=Count("id", filter=Q(validation_status="rejected")),
    )
    stats["favorites"] = Favorite.objects.filter(user=user).count()
    return stats


def _serialize_activity(activity):
    from django.utils.timesince import timesince
    icons = {
        "created": "[Created]", "updated": "[Updated]", "deleted": "[Deleted]",
        "status_changed": "[Status]", "favorited": "[Starred]", "unfavorited": "[Unstarred]",
    }
    return {
        "icon":           icons.get(activity.action, ""),
        "action_display": activity.get_action_display(),
        "poster_title":   activity.poster_title or "Unknown",
        "time":           timesince(activity.timestamp) + " ago",
        "user":           activity.user.username if activity.user else "System",
    }


@login_required(login_url="login")
def tags_autocomplete(request):
    q = request.GET.get("q", "").strip().lower()
    if not q or len(q) < 2:
        return JsonResponse([], safe=False)

    all_tags = (
        ResearchPoster.objects
        .exclude(tags__isnull=True)
        .exclude(tags="")
        .filter(tags__icontains=q)
        .values_list("tags", flat=True)
    )

    tag_counts = {}
    for tag_str in all_tags:
        for t in tag_str.split(","):
            t = t.strip()
            if t:
                key = t.lower()
                if q in key:
                    if key not in tag_counts:
                        tag_counts[key] = {"label": t, "count": 0}
                    tag_counts[key]["count"] += 1

    results = sorted(tag_counts.values(), key=lambda x: -x["count"])[:15]
    return JsonResponse([r["label"] for r in results], safe=False)


WEB_UPLOAD_COOLDOWN = 60


@login_required(login_url="login")
def upload_poster(request):
    if request.method == "POST":
        rate_key = f"web:upload_ratelimit:{request.user.pk}"
        if cache.get(rate_key):
            messages.warning(
                request,
                "You are uploading too quickly. Please wait a minute before uploading again.",
            )
            return redirect("upload")

        form = PosterUploadForm(request.POST, request.FILES)
        if form.is_valid():
            cache.set(rate_key, 1, timeout=WEB_UPLOAD_COOLDOWN)
            poster_temp                 = form.save(commit=False)
            poster_temp.uploaded_by     = request.user
            poster_temp.upload_source   = 'web'
            poster_temp.analysis_status = 'processing'
            poster_temp.save()

            user_notes = form.cleaned_data.get("notes", "") or ""
            user_tags  = form.cleaned_data.get("tags", "") or ""

            task = process_poster_task.delay(
                poster_id=poster_temp.pk,
                user_notes=user_notes,
                user_tags=user_tags,
                source="web",
                user_id=request.user.pk,
            )
            cache.set(f"task:poster:{poster_temp.pk}", task.id, timeout=3600)

            messages.info(
                request,
                "Poster uploaded. AI analysis is in progress. "
                "The paper will appear in your dashboard shortly."
            )
            return redirect(f"/dashboard/?task_id={task.id}")
    else:
        form = PosterUploadForm()

    recent_uploads = (
        ResearchPoster.objects
        .filter(uploaded_by=request.user, upload_source="web")
        .order_by("-created_at")[:3]
    )
    return render(request, "upload.html", {"form": form, "recent_uploads": recent_uploads})


@login_required(login_url="login")
def task_status(request, task_id):
    result = AsyncResult(task_id)
    data   = {"state": result.state}

    if result.state == "SUCCESS":
        task_result       = result.result or {}
        data["poster_id"] = task_result.get("poster_id")
        data["status"]    = task_result.get("status", "done")
        data["title"]     = task_result.get("title", "")
        if task_result.get("status") in ("duplicate", "rejected", "analysis_failed"):
            data["warning"] = task_result.get("reason") or task_result.get("status")

    elif result.state == "FAILURE":
        data["error"] = str(result.result)

    return JsonResponse(data)


@login_required(login_url="login")
def dashboard(request):
    posters = _apply_filters(
        ResearchPoster.objects.select_related("uploaded_by").all(),
        request.GET,
        favorite_user=request.user,
    )
    stats = _get_stats(request.user)

    SORT_FIELDS = {
        "title": "title", "category": "category",
        "status": "validation_status", "date": "created_at",
    }
    sort_by     = request.GET.get("sort", "date")
    sort_order  = request.GET.get("order", "desc")
    order_field = SORT_FIELDS.get(sort_by, "created_at")
    posters     = posters.order_by(order_field if sort_order == "asc" else f"-{order_field}")

    try:
        per_page = min(max(int(request.GET.get("per_page", 15)), 10), 100)
    except ValueError:
        per_page = 15

    paginator = Paginator(posters, per_page)
    page_obj  = paginator.get_page(request.GET.get("page", 1))

    poster_ids   = [p.id for p in page_obj.object_list]
    favorite_ids = set(
        Favorite.objects.filter(
            user=request.user,
            poster_id__in=poster_ids,
        ).values_list("poster_id", flat=True)
    )

    for poster in page_obj:
        poster.is_incomplete = not poster.paper_link or not poster.github_link
        poster.is_favorite   = poster.id in favorite_ids

    subfield_params = request.GET.getlist("subfield")
    if not subfield_params:
        sf_single       = request.GET.get("subfield", "")
        subfield_params = [s.strip() for s in sf_single.split(",") if s.strip()] if sf_single else []

    context = {
        "posters":            page_obj,
        "page_obj":           page_obj,
        "paginator":          paginator,
        "per_page":           per_page,
        "stats":              stats,
        "search_query":       request.GET.get("search", ""),
        "status_filter":      request.GET.get("status", ""),
        "category_filter":    request.GET.get("category", ""),
        "subfield_filter":    subfield_params,
        "has_github_filter":  request.GET.get("has_github", ""),
        "has_paper_filter":   request.GET.get("has_paper", ""),
        "favorites_filter":   request.GET.get("favorites", ""),
        "categories":         ResearchPoster.CATEGORY_CHOICES,
        "subfields_grouped":  ResearchPoster.SUBFIELDS_GROUPED,
        "recent_activity":    ActivityLog.objects.select_related("user").order_by("-timestamp")[:5],
        "author_filter":      request.GET.get("author", ""),
        "summary_filter":     request.GET.get("summary", ""),
        "date_from_filter":   request.GET.get("date_from", ""),
        "date_to_filter":     request.GET.get("date_to", ""),
        "year_from_filter":   request.GET.get("year_from", ""),
        "year_to_filter":     request.GET.get("year_to", ""),
        "sort_by":            sort_by,
        "sort_order":         sort_order,
        "pending_task_id":    request.GET.get("task_id", ""),
        "has_active_filters": bool(
            request.GET.get("search") or request.GET.get("status") or
            request.GET.get("category") or request.GET.get("author") or
            request.GET.get("summary") or request.GET.get("date_from") or
            request.GET.get("date_to") or request.GET.get("year_from") or
            request.GET.get("year_to") or request.GET.get("has_github") or
            request.GET.get("has_paper") or request.GET.get("favorites") or
            request.GET.get("subfield")
        ),
    }

    if request.GET.get("_ajax"):
        table_html        = render_to_string("_dashboard_partial.html", context, request=request)
        pagination_html   = render_to_string("_pagination_partial.html", context, request=request)
        cat               = context["category_filter"]
        subfields_for_cat = []
        if cat:
            for slug, label, items in ResearchPoster.SUBFIELDS_GROUPED:
                if slug == cat:
                    subfields_for_cat = [{"value": v, "label": l} for v, l in items]
                    break
        return JsonResponse({
            "table_html":        table_html,
            "pagination_html":   pagination_html,
            "stats":             stats,
            "category_filter":   cat,
            "subfields_for_cat": subfields_for_cat,
            "subfield_filter":   subfield_params,
            "total_count":       paginator.count,
        })

    return render(request, "dashboard.html", context)


@login_required(login_url="login")
def poster_detail(request, poster_id):
    poster      = get_object_or_404(ResearchPoster.objects.select_related("uploaded_by"), id=poster_id)
    is_favorite = Favorite.objects.filter(user=request.user, poster=poster).exists()
    return render(request, "poster_detail.html", {
        "poster":       poster,
        "is_favorite":  is_favorite,
        "tags_display": poster.tags_list,
    })


@login_required(login_url="login")
def edit_poster(request, poster_id):
    poster = get_object_or_404(ResearchPoster, id=poster_id)
    if request.method == "POST":
        form = PosterEditForm(request.POST, instance=poster)
        if form.is_valid():
            form.save()
            ActivityLog.objects.create(
                user=request.user, poster=poster, action="updated",
                poster_title=poster.title,
                details=f'Paper "{poster.title}" updated',
            )
            messages.success(request, "Paper updated successfully!")
            return redirect("dashboard")
    else:
        form = PosterEditForm(instance=poster)
    return render(request, "edit_poster.html", {"form": form, "poster": poster})


@login_required(login_url="login")
def update_status(request, poster_id):
    if request.method == "POST":
        poster     = get_object_or_404(ResearchPoster, id=poster_id)
        new_status = request.POST.get("status")
        if new_status in ("pending", "approved", "rejected"):
            old_status               = poster.validation_status
            poster.validation_status = new_status
            poster.save(update_fields=["validation_status", "updated_at"])
            activity = ActivityLog.objects.create(
                user=request.user, poster=poster, action="status_changed",
                poster_title=poster.title,
                details=f"Status: {old_status} → {new_status}",
            )
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({
                    "success":    True,
                    "new_status": new_status,
                    "message":    f"Status updated to {new_status.capitalize()}!",
                    "stats":      _get_stats(request.user),
                    "activity":   _serialize_activity(activity),
                })
            messages.success(request, f"Status updated to {new_status.capitalize()}!")
    return redirect("dashboard")


@login_required(login_url="login")
def delete_poster(request, poster_id):
    if request.method == "POST":
        poster = get_object_or_404(ResearchPoster, id=poster_id)
        title  = poster.title

        if poster.image:
            try:
                if os.path.isfile(poster.image.path):
                    os.remove(poster.image.path)
            except Exception:
                pass

        activity = ActivityLog.objects.create(
            user=request.user, poster=None, action="deleted",
            poster_title=title,
            details=f'Paper "{title}" deleted',
        )
        poster.delete()

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "success":  True,
                "message":  f'Paper "{title}" deleted successfully!',
                "stats":    _get_stats(request.user),
                "activity": _serialize_activity(activity),
            })
        messages.success(request, f'Paper "{title}" deleted successfully!')
    return redirect("dashboard")


@login_required(login_url="login")
def toggle_favorite(request, poster_id):
    if request.method == "POST":
        poster            = get_object_or_404(ResearchPoster, id=poster_id)
        favorite, created = Favorite.objects.get_or_create(user=request.user, poster=poster)

        if created:
            is_favorite = True
            action      = "favorited"
        else:
            favorite.delete()
            is_favorite = False
            action      = "unfavorited"

        activity = ActivityLog.objects.create(
            user=request.user, poster=poster, action=action,
            poster_title=poster.title,
            details=f'Paper "{poster.title}" {action}',
        )
        return JsonResponse({
            "success":     True,
            "is_favorite": is_favorite,
            "stats":       _get_stats(request.user),
            "activity":    _serialize_activity(activity),
        })
    return JsonResponse({"success": False}, status=400)


@login_required(login_url="login")
def update_notes(request, poster_id):
    if request.method == "POST":
        poster = get_object_or_404(ResearchPoster, id=poster_id)
        try:
            notes = json.loads(request.body).get("notes", "").strip()
        except (json.JSONDecodeError, AttributeError):
            notes = request.POST.get("notes", "").strip()

        if len(notes) > 500:
            return JsonResponse({"success": False, "message": "Notes too long (max 500 characters)."}, status=400)
        poster.notes = notes
        poster.save(update_fields=["notes", "updated_at"])

        activity = ActivityLog.objects.create(
            user=request.user, poster=poster, action="updated",
            poster_title=poster.title,
            details="Notes updated",
        )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "success":  True,
                "message":  "Notes saved!",
                "activity": _serialize_activity(activity),
            })
        messages.success(request, "Notes saved!")
        return redirect("dashboard")
    return JsonResponse({"success": False}, status=400)


@login_required(login_url="login")
def bulk_action(request):
    if request.method != "POST":
        return JsonResponse({"success": False}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    ids    = data.get("ids", [])
    action = data.get("action", "")

    if not ids:
        return JsonResponse({"success": False, "error": "No papers selected"}, status=400)

    posters = ResearchPoster.objects.filter(id__in=ids)
    count   = posters.count()

    if action in ("pending", "approved", "rejected"):
        for poster in posters:
            old = poster.validation_status
            poster.validation_status = action
            poster.save(update_fields=["validation_status", "updated_at"])
            ActivityLog.objects.create(
                user=request.user, poster=poster, action="status_changed",
                poster_title=poster.title,
                details=f"Bulk status: {old} → {action}",
            )
        message = f"{count} papers set to {action.capitalize()}"

    elif action == "delete":
        for poster in posters:
            if poster.image:
                try:
                    if os.path.isfile(poster.image.path):
                        os.remove(poster.image.path)
                except Exception:
                    pass
            ActivityLog.objects.create(
                user=request.user, poster=None, action="deleted",
                poster_title=poster.title,
                details=f'Paper "{poster.title}" deleted (bulk)',
            )
        posters.delete()
        message = f"{count} papers deleted"

    elif action == "favorite":
        changed = 0
        for poster in posters:
            _, created = Favorite.objects.get_or_create(user=request.user, poster=poster)
            if created:
                changed += 1
                ActivityLog.objects.create(
                    user=request.user, poster=poster, action="favorited",
                    poster_title=poster.title,
                    details=f'Paper "{poster.title}" favorited (bulk)',
                )
        message = f"{changed} papers starred"

    elif action == "unfavorite":
        favorites    = Favorite.objects.filter(user=request.user, poster__in=posters)
        favorite_ids = set(favorites.values_list("poster_id", flat=True))
        favorites.delete()
        changed = 0
        for poster in posters:
            if poster.id in favorite_ids:
                changed += 1
                ActivityLog.objects.create(
                    user=request.user, poster=poster, action="unfavorited",
                    poster_title=poster.title,
                    details=f'Paper "{poster.title}" unfavorited (bulk)',
                )
        message = f"{changed} papers unstarred"

    else:
        return JsonResponse({"success": False, "error": "Unknown action"}, status=400)

    return JsonResponse({
        "success": True,
        "message": message,
        "stats":   _get_stats(request.user),
        "action":  action,
    })


@login_required(login_url="login")
def delete_all_activities(request):
    if request.method == "POST":
        count = ActivityLog.objects.count()
        ActivityLog.objects.all().delete()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": True, "message": f"Successfully deleted {count} activity logs"})
        messages.success(request, f"Successfully deleted {count} activity logs")
        return redirect("dashboard")
    return JsonResponse({"success": False, "error": "Invalid request method"})


@login_required(login_url="login")
def retry_analysis(request, poster_id):
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)
    poster = get_object_or_404(ResearchPoster, id=poster_id)
    if poster.analysis_status != 'failed':
        return JsonResponse({"success": False, "error": "Paper is not in failed state"}, status=400)
    poster.analysis_status = 'processing'
    poster.save(update_fields=["analysis_status", "updated_at"])
    task = process_poster_task.delay(
        poster_id=poster.pk,
        user_notes=poster.notes or "",
        user_tags=poster.tags or "",
        source="web",
        user_id=request.user.pk,
    )
    cache.set(f"task:poster:{poster.pk}", task.id, timeout=3600)
    return JsonResponse({"success": True, "task_id": task.id})


@login_required(login_url="login")
def stop_analysis(request, poster_id):
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)
    poster = get_object_or_404(ResearchPoster, id=poster_id)

    task_id = cache.get(f"bot:task:{poster_id}") or cache.get(f"task:poster:{poster_id}")
    if task_id:
        try:
            celery_app.control.revoke(task_id, terminate=True)
        except Exception as e:
            logger.warning("Could not revoke task %s: %s", task_id, e)
        cache.delete(f"bot:task:{poster_id}")
        cache.delete(f"task:poster:{poster_id}")

    context = cache.get(f"bot:context:{poster_id}")
    if context:
        platform  = context["platform"]
        recipient = context["recipient"]
        _del_pending(platform, recipient)
        _clear_ratelimit(platform, recipient)
        cache.delete(f"bot:context:{poster_id}")
        send_message(platform, recipient, MESSAGE_TEMPLATES["analysis_failed"][platform])

    poster.analysis_status = 'failed'
    if poster.title in ("Pending analysis…", ""):
        poster.title = "Analysis Stopped"
    poster.save(update_fields=["title", "analysis_status", "updated_at"])

    return JsonResponse({"success": True, "message": "Analysis stopped"})

 
@login_required(login_url="login")
def dashboard_live_status(request):
    from django.db.models import Max
    processing = ResearchPoster.objects.filter(analysis_status='processing').count()
    latest_id  = ResearchPoster.objects.aggregate(m=Max('id'))['m'] or 0
    return JsonResponse({'processing': processing, 'latest_id': latest_id})


EXPORT_FIELDS = [
    "ID", "Title", "Authors", "Year", "Category", "Tags",
    "Paper Link", "GitHub Link", "Summary", "Why Useful",
    "Status", "Source", "Uploaded By", "Created At",
]


def _get_export_queryset(request):
    return (
        _apply_filters(
            ResearchPoster.objects.select_related("uploaded_by").all(),
            request.GET,
            favorite_user=request.user,
        )
        .filter(validation_status="approved")
        .order_by("-created_at")
    )


def _poster_to_row(poster):
    return [
        poster.id, poster.title, poster.authors,
        poster.publication_year or "",
        poster.get_category_display(), poster.tags or "",
        poster.paper_link or "", poster.github_link or "",
        poster.summary, poster.why_useful or "",
        poster.validation_status,
        poster.get_upload_source_display(),
        poster.uploaded_by.username if poster.uploaded_by else "",
        poster.created_at.strftime("%Y-%m-%d %H:%M"),
    ]


@login_required(login_url="login")
def export_approved_csv(request):
    posters  = _get_export_queryset(request)
    filename = f"approved_posters_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response, delimiter=";")
    writer.writerow(EXPORT_FIELDS)
    for p in posters:
        writer.writerow(_poster_to_row(p))
    return response


@login_required(login_url="login")
def export_approved_json(request):
    posters  = _get_export_queryset(request)
    filename = f"approved_posters_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload  = {
        "exported_at": timezone.now().isoformat(),
        "count":       posters.count(),
        "items": [
            {
                "id":            p.id,
                "title":            p.title,
                "authors":          p.authors,
                "publication_year": p.publication_year,
                "category":         p.get_category_display(),
                "tags":          p.tags or "",
                "paper_link":    p.paper_link or "",
                "github_link":   p.github_link or "",
                "description":   p.summary,
                "why_useful":    p.why_useful or "",
                "status":        p.validation_status,
                "upload_source": p.get_upload_source_display(),
                "uploaded_by":   p.uploaded_by.username if p.uploaded_by else "",
                "created_at":    p.created_at.isoformat(),
                "updated_at":    p.updated_at.isoformat(),
            }
            for p in posters
        ],
    }
    response = HttpResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@csrf_exempt
def telegram_webhook(request):
    if request.method != "POST":
        return HttpResponse("Telegram Bot Active", status=200)

    _tg_secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    if _tg_secret:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_secret != _tg_secret:
            return HttpResponse("Forbidden", status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))

        if "callback_query" in data:
            cb      = data["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            cb_data = cb.get("data", "")
            answer_telegram_callback(cb["id"])
            _handle_pending_callback("telegram", chat_id, cb_data)
            return HttpResponse("OK", status=200)

        if "message" not in data:
            return HttpResponse("OK")

        chat_id = data["message"]["chat"]["id"]
        message = data["message"]

        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            caption = message.get("caption", "").strip()
            download_and_handle_media_task.delay(
                "telegram", chat_id,
                file_id,
                f"tg_{file_id}.jpg",
                caption=caption or None,
            )

        elif "document" in message:
            doc     = message["document"]
            ext     = get_file_extension(doc.get("file_name", ""), doc.get("mime_type"))
            caption = message.get("caption", "").strip()
            download_and_handle_media_task.delay(
                "telegram", chat_id,
                doc["file_id"],
                f"tg_doc_{doc['file_id']}.{ext}",
                caption=caption or None,
            )

        elif "text" in message:
            text = message["text"].strip()
            if not _handle_pending_validation_text("telegram", chat_id, text):
                if text == "/start":
                    send_message("telegram", chat_id, MESSAGE_TEMPLATES["welcome"]["telegram"])
                    _set_welcomed("telegram", chat_id)
                elif text == "/help":
                    send_message("telegram", chat_id, MESSAGE_TEMPLATES["help"]["telegram"])
                elif text == "/dashboard":
                    _handle_dashboard_command("telegram", chat_id)
                elif text.startswith("/search"):
                    _handle_search_command("telegram", chat_id, text[7:].strip())
                elif not _is_welcomed("telegram", chat_id):
                    _set_welcomed("telegram", chat_id)
                    send_message("telegram", chat_id, MESSAGE_TEMPLATES["welcome"]["telegram"])
                else:
                    send_message("telegram", chat_id, MESSAGE_TEMPLATES["fallback"]["telegram"])

        else:
            if not _is_welcomed("telegram", chat_id):
                _set_welcomed("telegram", chat_id)
                send_message("telegram", chat_id, MESSAGE_TEMPLATES["welcome"]["telegram"])

    except Exception as e:
        logger.error("Telegram webhook error: %s", e)

    return HttpResponse("OK", status=200)


@csrf_exempt
def whatsapp_webhook(request):
    if request.method == "GET":
        mode      = request.GET.get("hub.mode")
        token     = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge, status=200)
        return HttpResponse("Forbidden", status=403)

    if request.method != "POST":
        return HttpResponse("OK", status=200)

    try:
        body    = json.loads(request.body.decode("utf-8"))
        changes = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})

        if "messages" not in changes:
            return HttpResponse("EVENT_RECEIVED", status=200)

        message  = changes["messages"][0]
        phone    = message["from"]
        msg_type = message["type"]

        if msg_type == "image":
            image_id = message["image"]["id"]
            caption  = message["image"].get("caption", "").strip()
            download_and_handle_media_task.delay(
                "whatsapp", phone,
                image_id,
                f"wa_{image_id}.jpg",
                caption=caption or None,
            )

        elif msg_type == "document":
            doc     = message["document"]
            ext     = get_file_extension(doc.get("filename", ""), doc.get("mime_type"))
            caption = doc.get("caption", "").strip()
            download_and_handle_media_task.delay(
                "whatsapp", phone,
                doc["id"],
                f"wa_doc_{doc['id']}.{ext}",
                caption=caption or None,
            )

        elif msg_type == "text":
            text_body = message["text"]["body"].strip()
            if not _handle_pending_validation_text("whatsapp", phone, text_body):
                lower = text_body.lower()
                if lower in ("start", "hi", "hello", "ciao", "help", "aiuto", "aide"):
                    send_message("whatsapp", phone, MESSAGE_TEMPLATES["help"]["whatsapp"])
                elif lower in ("dashboard", "stats", "statistiche"):
                    _handle_dashboard_command("whatsapp", phone)
                elif lower.startswith("search"):
                    _handle_search_command("whatsapp", phone, text_body[6:].strip())
                else:
                    send_message("whatsapp", phone, MESSAGE_TEMPLATES["fallback"]["whatsapp"])

        elif msg_type == "interactive":
            btn_id = message.get("interactive", {}).get("button_reply", {}).get("id", "")
            _handle_pending_callback("whatsapp", phone, btn_id)

        return HttpResponse("EVENT_RECEIVED", status=200)

    except Exception as e:
        logger.error("WhatsApp webhook error: %s", e)
        return HttpResponse("ERROR", status=200)