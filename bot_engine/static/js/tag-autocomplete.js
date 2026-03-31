
function initTagAutocomplete(inputId, opts) {
    opts = opts || {};
    var input       = document.getElementById(inputId);
    if (!input) return;

    var apiUrl      = opts.apiUrl || '/api/tags-autocomplete/';
    var minChars    = opts.minChars || 2;
    var debounceMs  = opts.debounce || 200;
    var onTagChange = opts.onTagChange || null;

    var dropdown    = null;
    var timer       = null;
    var activeIdx   = -1;
    var suggestions = [];

    dropdown = document.createElement('div');
    dropdown.className = 'tag-ac-dropdown';
    dropdown.style.cssText = 'display:none;position:absolute;left:0;right:0;z-index:100;' +
        'background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-md);' +
        'box-shadow:0 4px 16px rgba(0,0,0,.12);max-height:200px;overflow-y:auto;margin-top:2px;';
    input.parentElement.style.position = 'relative';
    input.parentElement.appendChild(dropdown);


    function getCurrentToken() {
        var val    = input.value;
        var cursor = input.selectionStart || val.length;
        var before = val.substring(0, cursor);
        var lastComma = before.lastIndexOf(',');
        return { text: before.substring(lastComma + 1).trim(), start: lastComma + 1, cursor: cursor };
    }

    function replaceToken(token, replacement) {
        var val    = input.value;
        var cursor = input.selectionStart || val.length;
        var before = val.substring(0, token.start);
        var after  = val.substring(cursor);

        if (before.length > 0 && before[before.length - 1] === ',') {
            before += ' ';
        }

        var suffix = after.trim() ? '' : ', ';
        if (after.trim() && !after.trim().startsWith(',')) {
            suffix = ', ';
        }

        input.value = before + replacement + suffix + after.trimStart();
        var newPos  = (before + replacement + suffix).length;
        input.setSelectionRange(newPos, newPos);
        input.focus();

        if (onTagChange) onTagChange();
    }

    function getExistingTags() {
        return input.value.split(',').map(function(t) { return t.trim().toLowerCase(); }).filter(Boolean);
    }

    function renderDropdown() {
        dropdown.innerHTML = '';
        if (!suggestions.length) { dropdown.style.display = 'none'; return; }

        var existing = getExistingTags();
        var filtered = suggestions.filter(function(s) { return existing.indexOf(s.toLowerCase()) === -1; });
        if (!filtered.length) { dropdown.style.display = 'none'; return; }

        filtered.forEach(function(tag, i) {
            var item = document.createElement('div');
            item.className = 'tag-ac-item';
            item.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:0.88em;color:var(--text-strong);' +
                'transition:background 0.1s;';
            item.textContent = tag;
            item.dataset.index = i;

            item.addEventListener('mouseenter', function() {
                activeIdx = i;
                highlightItem();
            });
            item.addEventListener('mousedown', function(e) {
                e.preventDefault();
                selectItem(i);
            });

            dropdown.appendChild(item);
        });

        activeIdx = -1;
        dropdown.style.display = 'block';
    }

    function highlightItem() {
        var items = dropdown.querySelectorAll('.tag-ac-item');
        items.forEach(function(el, i) {
            el.style.background = i === activeIdx ? 'var(--bg-hover, rgba(0,0,0,.05))' : '';
        });
    }

    function selectItem(idx) {
        var items = dropdown.querySelectorAll('.tag-ac-item');
        if (items[idx]) {
            var token = getCurrentToken();
            replaceToken(token, items[idx].textContent);
        }
        closeDropdown();
    }

    function closeDropdown() {
        dropdown.style.display = 'none';
        suggestions = [];
        activeIdx   = -1;
    }

    function fetchSuggestions(query) {
        if (!query || query.length < minChars) { closeDropdown(); return; }

        fetch(apiUrl + '?q=' + encodeURIComponent(query), {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            suggestions = data || [];
            renderDropdown();
        })
        .catch(function() { closeDropdown(); });
    }


    input.addEventListener('input', function() {
        clearTimeout(timer);
        var token = getCurrentToken();
        timer = setTimeout(function() { fetchSuggestions(token.text); }, debounceMs);
    });

    input.addEventListener('keydown', function(e) {
        if (dropdown.style.display === 'none') return;

        var items = dropdown.querySelectorAll('.tag-ac-item');
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIdx = (activeIdx + 1) % items.length;
            highlightItem();
            items[activeIdx].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIdx = activeIdx <= 0 ? items.length - 1 : activeIdx - 1;
            highlightItem();
            items[activeIdx].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            if (activeIdx >= 0) {
                e.preventDefault();
                selectItem(activeIdx);
            }
        } else if (e.key === 'Escape') {
            closeDropdown();
        }
    });

    input.addEventListener('blur', function() {
        setTimeout(closeDropdown, 150);
    });
}
