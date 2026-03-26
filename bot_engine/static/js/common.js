/* ─────────────────────────────────────────────────────────────
   COMMON UTILITIES — shared across all pages
   ───────────────────────────────────────────────────────────── */

function getCSRFToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;

    var cookie = document.cookie
        .split('; ')
        .find(function (c) { return c.startsWith('csrftoken='); });

    return cookie ? cookie.split('=')[1] : '';
}

/* ── Escape key closes any open modal ── */
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        var modal = document.getElementById('deleteModal');
        if (modal && modal.style.display !== 'none' && typeof closeDeleteModal === 'function') {
            closeDeleteModal();
        }
    }
});

function showToast(message, type) {
    type = type || 'success';

    var existing = document.getElementById('toast');
    if (existing) existing.remove();

    var icons = { success: '\u2713', error: '\u2715', info: '\u2139', warning: '\u26A0' };

    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.id = 'toast';
    toast.innerHTML =
        '<span class="toast-icon">' + (icons[type] || icons.info) + '</span>' +
        '<span class="toast-message">' + message + '</span>';

    document.body.appendChild(toast);

    var delay = type === 'warning' ? 5000 : 3000;
    setTimeout(function () {
        toast.classList.add('toast-hide');
        setTimeout(function () { toast.remove(); }, 300);
    }, delay);
}

