(function () {
    var form = document.getElementById('editForm');
    if (!form) return;
    var dot = document.getElementById('dirtyDot');
    var isDirty = false;

    function markDirty() {
        isDirty = true;
        if (dot) dot.classList.add('visible');
    }

    form.addEventListener('input', markDirty);
    form.addEventListener('change', markDirty);
    form.addEventListener('submit', function () {
        isDirty = false;
        if (dot) dot.classList.remove('visible');
    });

    window.addEventListener('beforeunload', function (e) {
        if (!isDirty) return;
        e.preventDefault();
        e.returnValue = '';
    });

    if (typeof initTagAutocomplete === 'function') {
        initTagAutocomplete('id_tags');
    }

    form.querySelectorAll('.subfield-checkbox-label input[type="checkbox"]').forEach(function (cb) {
        cb.addEventListener('change', function () {
            this.closest('.subfield-checkbox-label').classList.toggle('checked', this.checked);
        });
    });

    document.addEventListener('click', function (e) {
        var link = e.target.closest('[data-back-link]');
        if (!link) return;
        if (history.length > 1) {
            e.preventDefault();
            history.back();
        }
    });
})();
