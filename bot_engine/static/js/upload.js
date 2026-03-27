/* ─────────────────────────────────────────────────────────────
   UPLOAD PAGE  (requires common.js loaded first)
   ───────────────────────────────────────────────────────────── */

var MAX_SIZE_MB   = 20;
var ALLOWED_TYPES = ['image/jpeg','image/png','image/gif','image/webp','image/bmp','image/tiff'];

var dropZone    = document.getElementById('dropZone');
var fileInput   = document.getElementById('hiddenFileInput');
var dropIdle    = document.getElementById('dropIdle');
var dropPreview = document.getElementById('dropPreview');
var previewImg  = document.getElementById('previewImg');
var removeBtn   = document.getElementById('removeFile');
var metaBox     = document.getElementById('fileMetaInfo');
var fileNameVal = document.getElementById('fileNameValue');
var fileSizeVal = document.getElementById('fileSizeValue');
var fileDimVal  = document.getElementById('fileDimensionsValue');

function formatBytes(bytes) {
    if (!bytes) return '-';
    var kb = bytes / 1024, mb = kb / 1024;
    return mb >= 1 ? mb.toFixed(2) + ' MB' : kb.toFixed(1) + ' KB';
}

function showError(msg) {
    var box = document.getElementById('uploadError');
    document.getElementById('uploadErrorMsg').textContent = msg;
    box.style.display = 'flex';
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function dismissError() {
    document.getElementById('uploadError').style.display = 'none';
}

function resetDropZone() {
    dropIdle.style.display    = '';
    dropPreview.style.display = 'none';
    previewImg.src            = '';
    metaBox.style.display     = 'none';
    fileInput.value           = '';
    document.getElementById('uploadExtras').style.display = 'none';
}

function handleFile(file) {
    dismissError();
    if (!file) return;
    if (ALLOWED_TYPES.indexOf(file.type) === -1) {
        showError('"' + file.name + '" is not a valid image. Allowed: JPG, PNG, GIF, WEBP, BMP, TIFF.');
        resetDropZone(); return;
    }
    var sizeMB = file.size / (1024 * 1024);
    if (sizeMB > MAX_SIZE_MB) {
        showError('File too large (' + sizeMB.toFixed(1) + ' MB). Max allowed: ' + MAX_SIZE_MB + ' MB.');
        resetDropZone(); return;
    }
    var url = URL.createObjectURL(file);
    previewImg.onload = function () { URL.revokeObjectURL(url); };
    previewImg.src = url;
    dropIdle.style.display    = 'none';
    dropPreview.style.display = 'flex';
    fileNameVal.textContent = file.name;
    fileSizeVal.textContent = formatBytes(file.size);
    fileDimVal.textContent  = 'Loading\u2026';
    metaBox.style.display   = 'flex';
    document.getElementById('uploadExtras').style.display = 'block';
    var tempImg = new Image();
    var tempUrl = URL.createObjectURL(file);
    tempImg.onload = function () {
        fileDimVal.textContent = tempImg.naturalWidth + ' \u00D7 ' + tempImg.naturalHeight + ' px';
        URL.revokeObjectURL(tempUrl);
    };
    tempImg.src = tempUrl;
}

dropZone.addEventListener('click', function (e) {
    if (e.target === removeBtn || removeBtn.contains(e.target)) return;
    fileInput.click();
});
fileInput.addEventListener('change', function () {
    if (fileInput.files && fileInput.files[0]) handleFile(fileInput.files[0]);
});
removeBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    resetDropZone();
    dismissError();
});
dropZone.addEventListener('dragover', function (e) {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});
['dragleave', 'dragend'].forEach(function (ev) {
    dropZone.addEventListener(ev, function () { dropZone.classList.remove('drag-over'); });
});
dropZone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    var file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) {
        var dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        handleFile(file);
    }
});

/* ── Progress helpers ── */
var progressWrap   = document.getElementById('uploadProgressWrap');
var progressFill   = document.getElementById('progressFill');
var progressPct    = document.getElementById('progressPct');
var progressPhase  = document.getElementById('progressPhase');
var progressStatus = document.getElementById('progressStatus');

function setProgress(pct, phase, status) {
    progressFill.style.width = pct + '%';
    progressPct.textContent  = Math.round(pct) + '%';
    if (phase)  progressPhase.textContent  = phase;
    if (status) progressStatus.textContent = status;
}

function showProgress() {
    progressWrap.style.display = 'block';
    setProgress(0, 'Uploading\u2026', '');
}

document.getElementById('uploadForm').addEventListener('submit', function (e) {
    if (!fileInput.files || !fileInput.files[0]) {
        e.preventDefault();
        showError('Please select or drop an image before submitting.');
        return;
    }
    e.preventDefault();
    dismissError();

    var submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    showProgress();

    var formData = new FormData(document.getElementById('uploadForm'));
    var xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', function (ev) {
        if (ev.lengthComputable) {
            setProgress(
                (ev.loaded / ev.total) * 100,
                'Uploading\u2026',
                formatBytes(ev.loaded) + ' / ' + formatBytes(ev.total)
            );
        }
    });

    xhr.upload.addEventListener('load', function () {
        setProgress(100, 'Upload complete', 'Redirecting\u2026');
    });

    xhr.addEventListener('load', function () {
        if (xhr.status >= 200 && xhr.status < 400) {
            window.location.href = xhr.responseURL || '/dashboard/';
        } else {
            submitBtn.disabled = false;
            progressWrap.style.display = 'none';
            showError('Server error ' + xhr.status + '. Please try again.');
        }
    });

    xhr.addEventListener('error', function () {
        submitBtn.disabled = false;
        progressWrap.style.display = 'none';
        showError('Network error. Please check your connection and try again.');
    });

    xhr.open('POST', document.getElementById('uploadForm').action || window.location.href);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.send(formData);
});

/* ── Character counters ── */
(function () {
    function bindCounter(inputId, counterId, max) {
        var el = document.getElementById(inputId);
        var counter = document.getElementById(counterId);
        if (!el || !counter) return;
        counter.textContent = el.value.length;
        el.addEventListener('input', function () {
            counter.textContent = el.value.length;
            counter.parentElement.classList.toggle('over-limit', el.value.length >= max);
        });
    }
    bindCounter('id_notes', 'notesCharCount', 500);
    bindCounter('id_tags', 'tagsCharCount', 200);
})();

/* ── Tag chip preview ── */
function updateTagChips() {
    var el = document.getElementById('id_tags');
    var preview = document.getElementById('tagChipPreview');
    if (!el || !preview) return;
    preview.innerHTML = '';
    el.value.split(',').forEach(function (t) {
        t = t.trim();
        if (!t) return;
        var chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = t;
        preview.appendChild(chip);
    });
}

document.getElementById('id_tags').addEventListener('input', updateTagChips);

/* ── Tag autocomplete ── */
if (typeof initTagAutocomplete === 'function') {
    initTagAutocomplete('id_tags', { onTagChange: updateTagChips });
}
