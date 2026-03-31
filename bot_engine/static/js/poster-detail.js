
function copyDetailLink(text) {
    navigator.clipboard.writeText(text).then(function () {
        showToast('Link copied!');
    });
}

function confirmDeleteDetail(posterId, posterTitle) {
    document.getElementById('deletePosterTitle').textContent = posterTitle;
    document.getElementById('deleteForm').action = '/delete/' + posterId + '/';
    document.getElementById('deleteModal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('deleteModal').style.display = 'none';
}

function retryAnalysisDetail(posterId) {
    var btn = document.getElementById('retryBtn');
    if (!btn) return;
    var original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg> Retrying\u2026';

    fetch('/retry-analysis/' + posterId + '/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken(), 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
        if (!data.success) {
            btn.disabled = false; btn.innerHTML = original;
            showToast(data.error || 'Retry failed', 'error'); return;
        }
        showToast('Analysis restarted\u2026', 'info');
        var interval = setInterval(function () {
            fetch('/task-status/' + data.task_id + '/')
                .then(function (r) { return r.json(); })
                .then(function (stat) {
                    if (stat.state === 'SUCCESS') { clearInterval(interval); window.location.reload(); }
                    else if (stat.state === 'FAILURE') {
                        clearInterval(interval); btn.disabled = false; btn.innerHTML = original;
                        showToast('Analysis failed again', 'error');
                    }
                })
                .catch(function () {});
        }, 2000);
    })
    .catch(function () { btn.disabled = false; btn.innerHTML = original; showToast('Network error', 'error'); });
}

function stopAnalysisDetail(posterId) {
    var btn = document.getElementById('stopBtn');
    if (!btn) return;
    btn.disabled = true;
    fetch('/stop-analysis/' + posterId + '/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken(), 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
        if (data.success) { showToast('Analysis stopped', 'info'); setTimeout(function () { window.location.reload(); }, 700); }
        else { btn.disabled = false; showToast(data.error || 'Error', 'error'); }
    })
    .catch(function () { btn.disabled = false; showToast('Network error', 'error'); });
}

(function () {
    var btn = document.getElementById('backToTop');
    if (!btn) return;
    window.addEventListener('scroll', function () {
        btn.classList.toggle('visible', window.scrollY > 360);
    });
    btn.addEventListener('click', function () {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
})();
