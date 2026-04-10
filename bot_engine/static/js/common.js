
function getCSRFToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;

    var cookie = document.cookie
        .split('; ')
        .find(function (c) { return c.startsWith('csrftoken='); });

    return cookie ? cookie.split('=')[1] : '';
}


document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        var modal = document.getElementById('deleteModal');
        if (modal && modal.style.display !== 'none' && typeof closeDeleteModal === 'function') {
            closeDeleteModal();
        }
    }
});

/* Lightbox with zoom + pan */
var _lb = { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0 };

function _lbApply() {
    var img = document.getElementById('lightboxImg');
    if (img) img.style.transform = 'translate(' + _lb.x + 'px,' + _lb.y + 'px) scale(' + _lb.scale + ')';
}

function _lbReset() {
    _lb.scale = 1; _lb.x = 0; _lb.y = 0; _lb.dragging = false;
    var img = document.getElementById('lightboxImg');
    if (img) { img.style.transform = ''; img.style.cursor = 'zoom-in'; }
}

function openLightbox(src) {
    var lb = document.getElementById('lightbox');
    var img = document.getElementById('lightboxImg');
    if (!lb || !img) return;
    img.src = src;
    _lbReset();
    lb.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeLightbox(e) {
    var lb = document.getElementById('lightbox');
    if (!lb) return;
    if (e && e.target !== lb && !e.target.classList.contains('lightbox-close')) return;
    lb.classList.remove('active');
    document.body.style.overflow = '';
    _lbReset();
}

document.addEventListener('DOMContentLoaded', function() {
    var lb = document.getElementById('lightbox');
    if (!lb) return;
    var img = document.getElementById('lightboxImg');

    /* Wheel zoom */
    lb.addEventListener('wheel', function(e) {
        e.preventDefault();
        var prev = _lb.scale;
        _lb.scale = Math.min(Math.max(0.5, _lb.scale + (e.deltaY < 0 ? 0.2 : -0.2)), 8);
        if (_lb.scale <= 1) { _lb.x = 0; _lb.y = 0; }
        else { _lb.x *= _lb.scale / prev; _lb.y *= _lb.scale / prev; }
        img.style.cursor = _lb.scale > 1 ? 'grab' : 'zoom-in';
        _lbApply();
    }, { passive: false });

    /* Click to zoom in/out */
    img.addEventListener('click', function(e) {
        e.stopPropagation();
        if (_lb.scale > 1) { _lbReset(); _lbApply(); }
        else { _lb.scale = 2.5; img.style.cursor = 'grab'; _lbApply(); }
    });

    /* Drag to pan when zoomed */
    img.addEventListener('mousedown', function(e) {
        if (_lb.scale <= 1) return;
        e.preventDefault();
        _lb.dragging = true;
        _lb.startX = e.clientX - _lb.x;
        _lb.startY = e.clientY - _lb.y;
        img.style.cursor = 'grabbing';
    });
    document.addEventListener('mousemove', function(e) {
        if (!_lb.dragging) return;
        _lb.x = e.clientX - _lb.startX;
        _lb.y = e.clientY - _lb.startY;
        _lbApply();
    });
    document.addEventListener('mouseup', function() {
        if (_lb.dragging) { _lb.dragging = false; img.style.cursor = _lb.scale > 1 ? 'grab' : 'zoom-in'; }
    });

    /* Touch: pinch-to-zoom + drag */
    var lastDist = 0;
    lb.addEventListener('touchstart', function(e) {
        if (e.touches.length === 2) {
            lastDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
        } else if (e.touches.length === 1 && _lb.scale > 1) {
            _lb.dragging = true;
            _lb.startX = e.touches[0].clientX - _lb.x;
            _lb.startY = e.touches[0].clientY - _lb.y;
        }
    }, { passive: true });
    lb.addEventListener('touchmove', function(e) {
        if (e.touches.length === 2) {
            e.preventDefault();
            var dist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
            if (lastDist) { _lb.scale = Math.min(Math.max(0.5, _lb.scale * (dist / lastDist)), 8); _lbApply(); }
            lastDist = dist;
        } else if (e.touches.length === 1 && _lb.dragging) {
            e.preventDefault();
            _lb.x = e.touches[0].clientX - _lb.startX;
            _lb.y = e.touches[0].clientY - _lb.startY;
            _lbApply();
        }
    }, { passive: false });
    lb.addEventListener('touchend', function() { _lb.dragging = false; lastDist = 0; });

    /* Escape */
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && lb.classList.contains('active')) closeLightbox();
    });
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

