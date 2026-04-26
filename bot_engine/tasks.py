import logging
import os
import uuid

import redis
import requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections

logger = logging.getLogger(__name__)

LOCK_TIMEOUT = int(os.getenv("POSTER_PROCESSING_LOCK_TIMEOUT", "3600"))
STALE_PROCESSING_SECONDS = 600  
BOT_FAILURE_MESSAGE_TTL = 86400
BOT_SUCCESS_MESSAGE_TTL = 86400
BOT_CONTEXT_TTL = 86400
BOT_STATE_TTL = 7200

_UNLOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


_redis_client = None


def _get_redis_client():
    global _redis_client
    if _redis_client is None:
        redis_url = os.environ.get("REDIS_CACHE_URL") or getattr(
            settings, "CELERY_BROKER_URL", "redis://redis:6379/0"
        )
        _redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def _acquire_poster_lock(poster_id: int):
    client = _get_redis_client()
    lock_key = f"lock:poster:{poster_id}"
    token = uuid.uuid4().hex
    acquired = client.set(lock_key, token, ex=LOCK_TIMEOUT, nx=True)
    return client, lock_key, token, bool(acquired)


def _release_poster_lock(client, lock_key: str, token: str):
    try:
        client.eval(_UNLOCK_SCRIPT, 1, lock_key, token)
    except Exception as e:
        logger.warning("Could not release lock %s: %s", lock_key, e)


def _is_stale_processing(poster_id):
    """Check if a poster has been stuck in 'processing' longer than STALE_PROCESSING_SECONDS."""
    try:
        from bot_engine.models import ResearchPoster
        from django.utils import timezone

        poster = ResearchPoster.objects.filter(pk=poster_id, analysis_status='processing').first()
        if not poster:
            return False
        age = (timezone.now() - poster.updated_at).total_seconds()
        return age > STALE_PROCESSING_SECONDS
    except Exception:
        return False


def _force_break_lock(poster_id):
    """Force-delete a poster lock regardless of token ownership."""
    try:
        client = _get_redis_client()
        lock_key = f"lock:poster:{poster_id}"
        client.delete(lock_key)
        logger.info("Force-broke stale lock for poster_id=%s", poster_id)
    except Exception as e:
        logger.warning("Could not force-break lock for poster_id=%s: %s", poster_id, e)


def _mark_poster_processing(poster_id):
    try:
        from bot_engine.models import ResearchPoster

        poster = ResearchPoster.objects.filter(pk=poster_id).first()
        if not poster:
            return None

        if getattr(poster, "analysis_status", None) != "processing":
            poster.analysis_status = "processing"
            poster.save(update_fields=["analysis_status", "updated_at"])
        return poster
    except Exception as e:
        logger.warning("_mark_poster_processing error for poster %s: %s", poster_id, e)
        return None


def _mark_poster_failed(poster_id, title_fallback="Analysis Failed"):
    try:
        from bot_engine.models import ResearchPoster

        p = ResearchPoster.objects.filter(pk=poster_id).first()
        if p:
            p.analysis_status = "failed"
            if getattr(p, "title", "") in ("Pending analysis…", "", None):
                p.title = title_fallback
            p.save(update_fields=["title", "analysis_status", "updated_at"])
    except Exception as e:
        logger.warning("_mark_poster_failed error for poster %s: %s", poster_id, e)


def _delete_temp_poster(poster_id, log_prefix):
    try:
        from bot_engine.models import ResearchPoster

        p = ResearchPoster.objects.filter(pk=poster_id).first()
        if not p:
            return

        try:
            if p.image:
                p.image.delete(save=False)
        except Exception as e:
            logger.warning("[%s] Could not delete image for poster %s: %s", log_prefix, poster_id, e)

        try:
            p.delete()
        except Exception as e:
            logger.warning("[%s] Could not delete poster %s: %s", log_prefix, poster_id, e)

    except Exception as e:
        logger.warning("[%s] _delete_temp_poster failed for %s: %s", log_prefix, poster_id, e)


def _send_failed_with_retry(platform, recipient, poster_id):
    from bot_engine.views import send_message, send_telegram_buttons, MESSAGE_TEMPLATES

    text = MESSAGE_TEMPLATES["analysis_failed"][platform]

    if platform == "telegram":
        send_telegram_buttons(
            recipient,
            text,
            [{"text": "🔄 Retry Analysis", "callback_data": f"retry_{poster_id}"}],
        )

    elif platform == "whatsapp":
        try:
            response = requests.post(
                f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_ID}/messages",
                headers={
                    "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
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
                                {
                                    "type": "reply",
                                    "reply": {
                                        "id": f"retry_{poster_id}",
                                        "title": "🔄 Retry",
                                    },
                                },
                            ]
                        },
                    },
                },
                timeout=8,
            )
            response.raise_for_status()
        except Exception as e:
            logger.warning("WhatsApp retry button send failed: %s", e)
            send_message(platform, recipient, text)

    else:
        send_message(platform, recipient, text)


def _send_failed_with_retry_once(platform, recipient, poster_id):
    once_key = f"bot:failed-message:{platform}:{recipient}:{poster_id}"
    if not cache.add(once_key, "1", timeout=BOT_FAILURE_MESSAGE_TTL):
        logger.info(
            "[Task:bot] failure message already sent for platform=%s recipient=%s poster_id=%s",
            platform, recipient, poster_id
        )
        return
    _send_failed_with_retry(platform, recipient, poster_id)


def _send_success_once(platform, recipient, poster):
    from bot_engine.views import _send_analysis_result, send_confirmation_buttons

    once_key = f"bot:success-message:{platform}:{recipient}:{poster.pk}"
    if not cache.add(once_key, "1", timeout=BOT_SUCCESS_MESSAGE_TTL):
        logger.info(
            "[Task:bot] success message already sent for platform=%s recipient=%s poster_id=%s",
            platform, recipient, poster.pk
        )
        return

    _send_analysis_result(platform, recipient, poster)
    send_confirmation_buttons(platform, recipient, poster.paper_link or "Not found")


def _clear_bot_ratelimit(platform, recipient):
    try:
        from bot_engine.views import _clear_ratelimit
        _clear_ratelimit(platform, recipient)
    except Exception as e:
        logger.warning("_clear_ratelimit failed for %s/%s: %s", platform, recipient, e)


@shared_task(bind=True, max_retries=5, default_retry_delay=15, acks_late=True, reject_on_worker_lost=True)
def process_poster_task(self, poster_id, user_notes=None, user_tags=None, source="web", user_id=None, group_ids=None):
    close_old_connections()

    lock_client = None
    lock_key = None
    lock_token = None

    try:
        lock_client, lock_key, lock_token, acquired = _acquire_poster_lock(poster_id)
    except Exception as e:
        logger.error("[Task:web] Could not acquire Redis lock for poster_id=%s: %s", poster_id, e)
        raise

    if not acquired:
        if _is_stale_processing(poster_id):
            logger.warning("[Task:web] poster_id=%s stale processing detected, breaking lock", poster_id)
            _force_break_lock(poster_id)
            close_old_connections()
            raise self.retry(countdown=5)
        else:
            if self.request.retries >= self.max_retries:
                logger.error("[Task:web] poster_id=%s lock retries exhausted, marking failed", poster_id)
                _mark_poster_failed(poster_id)
                close_old_connections()
                return {"poster_id": poster_id, "status": "analysis_failed"}
            logger.info("[Task:web] poster_id=%s lock held, retrying later (attempt %d/%d)",
                        poster_id, self.request.retries, self.max_retries)
            close_old_connections()
            raise self.retry(countdown=30)

    try:
        from bot_engine.models import ResearchPoster
        from bot_engine.views import process_uploaded_poster
        from django.contrib.auth import get_user_model

        User = get_user_model()
        activity_user = User.objects.filter(pk=user_id).first() if user_id else None

        logger.info("[Task:web] Starting analysis poster_id=%d source=%s", poster_id, source)

        poster = _mark_poster_processing(poster_id)
        if not poster:
            logger.error("[Task:web] Poster %d not found in DB", poster_id)
            return {"error": "poster not found"}

        new_poster, _, error = process_uploaded_poster(
            image_content=None,
            filename=None,
            source=source,
            existing_poster=poster,
            user_notes=user_notes,
            user_tags=user_tags,
            activity_user=activity_user,
            group_ids=group_ids,
        )

        if error == "no_text":
            _delete_temp_poster(poster_id, "Task:web")
            logger.info("[Task:web] poster_id=%d deleted (no_text)", poster_id)
            return {"poster_id": poster_id, "status": "rejected", "reason": "no_text"}

        if error == "duplicate":
            dup_id = new_poster.pk if new_poster else None
            if not new_poster or poster_id != new_poster.pk:
                _delete_temp_poster(poster_id, "Task:web")
            logger.info("[Task:web] poster_id=%d -> duplicate of %s", poster_id, dup_id)
            return {"poster_id": poster_id, "status": "duplicate", "duplicate_id": dup_id}

        if error == "analysis_failed":
            resolved = new_poster or ResearchPoster.objects.filter(pk=poster_id).first()
            resolved_id = resolved.pk if resolved else poster_id
            _mark_poster_failed(resolved_id)
            logger.warning("[Task:web] poster_id=%d -> analysis_failed, kept in DB", poster_id)
            return {"poster_id": resolved_id, "status": "analysis_failed"}

        if error:
            _delete_temp_poster(poster_id, "Task:web")
            logger.warning("[Task:web] poster_id=%d -> AI failed, deleted: %s", poster_id, error)
            return {"poster_id": poster_id, "status": "error"}

        resolved = new_poster or ResearchPoster.objects.filter(pk=poster_id).first()
        resolved_title = resolved.title if resolved else ""
        resolved_id = resolved.pk if resolved else poster_id

        logger.info("[Task:web] Completed poster_id=%d title='%s'", resolved_id, resolved_title)
        return {"poster_id": resolved_id, "title": resolved_title, "status": "done"}

    except Exception as exc:
        logger.error("[Task:web] Error on poster_id=%d: %s", poster_id, exc)

        if self.request.retries >= self.max_retries:
            _mark_poster_failed(poster_id)
            if lock_client and lock_key and lock_token:
                _release_poster_lock(lock_client, lock_key, lock_token)
            close_old_connections()
            return {"poster_id": poster_id, "status": "analysis_failed"}

        if lock_client and lock_key and lock_token:
            _release_poster_lock(lock_client, lock_key, lock_token)
        close_old_connections()
        raise self.retry(exc=exc)

    finally:
        if lock_client and lock_key and lock_token:
            _release_poster_lock(lock_client, lock_key, lock_token)
        close_old_connections()


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def download_and_handle_media_task(self, platform, recipient, media_id, filename, caption=None):
    close_old_connections()
    try:
        from bot_engine.views import (
            download_whatsapp_media,
            download_telegram_file,
            _handle_media_upload,
            send_message,
        )

        if platform == "whatsapp":
            media_content = download_whatsapp_media(media_id)
        else:
            media_content = download_telegram_file(media_id)

        close_old_connections()
        _handle_media_upload(platform, recipient, media_content, filename, caption=caption)

    except Exception as exc:
        logger.error("[Task:media] %s %s/%s: %s", platform, recipient, media_id, exc)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        try:
            from bot_engine.views import send_message
            send_message(platform, recipient, "❌ Error processing your image. Please try again.")
        except Exception:
            pass
    finally:
        close_old_connections()


@shared_task(bind=True, max_retries=5, default_retry_delay=15, acks_late=True, reject_on_worker_lost=True)
def process_bot_poster_task(self, platform, recipient, poster_id, notes=None, tags=None, user_id=None):
    close_old_connections()

    cache_key = f"bot:{platform}:{recipient}"
    lock_client = None
    lock_key = None
    lock_token = None

    try:
        lock_client, lock_key, lock_token, acquired = _acquire_poster_lock(poster_id)
    except Exception as e:
        logger.error("[Task:bot] Could not acquire Redis lock for poster_id=%s: %s", poster_id, e)
        raise

    if not acquired:
        if _is_stale_processing(poster_id):
            logger.warning("[Task:bot] poster_id=%s stale processing detected, breaking lock", poster_id)
            _force_break_lock(poster_id)
            close_old_connections()
            raise self.retry(countdown=5)
        else:
            if self.request.retries >= self.max_retries:
                logger.error("[Task:bot] poster_id=%s lock retries exhausted, marking failed", poster_id)
                _mark_poster_failed(poster_id)
                cache.delete(cache_key)
                _clear_bot_ratelimit(platform, recipient)
                close_old_connections()
                return {"status": "analysis_failed", "poster_id": poster_id}
            logger.info("[Task:bot] poster_id=%s lock held, retrying later (attempt %d/%d)",
                        poster_id, self.request.retries, self.max_retries)
            close_old_connections()
            raise self.retry(countdown=30)

    try:
        from bot_engine.models import ResearchPoster, UserGroupMembership
        from bot_engine.views import (
            process_uploaded_poster,
            send_message,
            MESSAGE_TEMPLATES,
        )
        from django.contrib.auth import get_user_model

        logger.info("[Task:bot] Starting analysis poster_id=%d platform=%s", poster_id, platform)

        poster = _mark_poster_processing(poster_id)
        if not poster:
            cache.delete(cache_key)
            _clear_bot_ratelimit(platform, recipient)
            logger.error("[Task:bot] Poster %d not found in DB", poster_id)
            return {"error": "poster not found"}

        User = get_user_model()
        activity_user = User.objects.filter(pk=user_id).first() if user_id else None
        group_ids = []
        if activity_user:
            primary_group_id = (
                UserGroupMembership.objects
                .filter(user=activity_user, is_primary=True)
                .values_list("group_id", flat=True)
                .first()
            )
            if primary_group_id:
                group_ids = [primary_group_id]

        new_poster, _, error = process_uploaded_poster(
            image_content=None,
            filename=None,
            source=platform,
            existing_poster=poster,
            user_notes=notes,
            user_tags=tags or None,
            activity_user=activity_user,
            group_ids=group_ids or None,
        )

        if error == "no_text":
            _delete_temp_poster(poster_id, "Task:bot")
            cache.delete(cache_key)
            _clear_bot_ratelimit(platform, recipient)
            send_message(platform, recipient, MESSAGE_TEMPLATES["no_text"][platform])
            logger.info("[Task:bot] poster_id=%d -> no_text", poster_id)
            return {"status": "no_text", "poster_id": poster_id}

        if error == "duplicate":
            dup_poster = new_poster
            if not dup_poster or poster_id != dup_poster.pk:
                _delete_temp_poster(poster_id, "Task:bot")

            cache.delete(cache_key)
            _clear_bot_ratelimit(platform, recipient)

            dup_title = dup_poster.title if dup_poster else "Unknown"
            paper_link = getattr(dup_poster, "paper_link", "") or ""
            if paper_link:
                if platform == "telegram":
                    link_line = f'🔗 <a href="{paper_link}">View paper</a>\n'
                else:
                    link_line = f"🔗 {paper_link}\n"
            else:
                link_line = ""
            msg = (
                MESSAGE_TEMPLATES["duplicate"][platform]
                .replace("{title}", dup_title)
                .replace("{paper_link_line}", link_line)
            )
            send_message(platform, recipient, msg)
            logger.info("[Task:bot] poster_id=%d -> duplicate '%s'", poster_id, dup_title)
            return {"status": "duplicate", "poster_id": poster_id}

        if error == "analysis_failed":
            resolved = new_poster or ResearchPoster.objects.filter(pk=poster_id).first()
            resolved_id = resolved.pk if resolved else poster_id

            _mark_poster_failed(resolved_id)
            cache.delete(cache_key)
            _clear_bot_ratelimit(platform, recipient)

            cache.set(
                f"bot:context:{resolved_id}",
                {"platform": platform, "recipient": recipient},
                timeout=BOT_CONTEXT_TTL,
            )
            _send_failed_with_retry_once(platform, recipient, resolved_id)
            logger.warning("[Task:bot] poster_id=%d -> analysis_failed, retry button sent", poster_id)
            return {"status": "analysis_failed", "poster_id": resolved_id}

        if error:
            _delete_temp_poster(poster_id, "Task:bot")
            cache.delete(cache_key)
            _clear_bot_ratelimit(platform, recipient)
            send_message(platform, recipient, "❌ Analysis could not be completed. Please try sending the image again.")
            logger.warning("[Task:bot] poster_id=%d -> error: %s", poster_id, error)
            return {"status": "error", "poster_id": poster_id}

        resolved = new_poster or ResearchPoster.objects.filter(pk=poster_id).first()
        if not resolved:
            cache.delete(cache_key)
            _clear_bot_ratelimit(platform, recipient)
            logger.error("[Task:bot] Resolved poster missing after processing poster_id=%d", poster_id)
            return {"status": "error", "poster_id": poster_id}

        logger.info("[Task:bot] Completed poster_id=%d title='%s'", resolved.pk, resolved.title)

        _send_success_once(platform, recipient, resolved)

        cache.set(
            cache_key,
            {"poster_id": resolved.pk, "state": "awaiting_confirmation"},
            timeout=BOT_STATE_TTL,
        )
        _clear_bot_ratelimit(platform, recipient)

        return {"status": "done", "poster_id": resolved.pk, "title": resolved.title}

    except Exception as exc:
        logger.error("[Task:bot] Error on poster_id=%d: %s", poster_id, exc)
        _clear_bot_ratelimit(platform, recipient)

        if self.request.retries >= self.max_retries:
            _mark_poster_failed(poster_id)
            cache.delete(cache_key)
            try:
                _send_failed_with_retry_once(platform, recipient, poster_id)
            except Exception as send_exc:
                logger.warning("[Task:bot] could not send final failure message: %s", send_exc)

            return {"status": "analysis_failed", "poster_id": poster_id}

        raise self.retry(exc=exc)

    finally:
        if lock_client and lock_key and lock_token:
            _release_poster_lock(lock_client, lock_key, lock_token)
        close_old_connections()