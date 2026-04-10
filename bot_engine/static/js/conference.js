(function () {
    'use strict';

    var CONF_LABELS = {
        cvpr:    'CVPR',
        iccv:    'ICCV',
        eccv:    'ECCV',
        wacv:    'WACV',
        miccai:  'MICCAI',
        isbi:    'ISBI',
        midl:    'MIDL',
        ipmi:    'IPMI',
        neurips: 'NeurIPS',
        icml:    'ICML',
        iclr:    'ICLR',
        aaai:    'AAAI',
        other:   'Other'
    };

    var form            = document.getElementById('confSearchForm');
    var confSelect      = document.getElementById('confConference');
    var otherWrap       = document.getElementById('confOtherWrap');
    var tagsInput       = document.getElementById('confTags');
    var tagChipsEl      = document.getElementById('confTagChips');
    var submitBtn       = document.getElementById('confSubmitBtn');
    var resultsArea     = document.getElementById('confResultsArea');
    var resultHeader    = document.getElementById('confResultHeader');
    var paperCard       = document.getElementById('confPaperCard');
    var similarSection  = document.getElementById('confSimilarSection');
    var similarList     = document.getElementById('confSimilarList');
    var similarFilters  = document.getElementById('confSimilarFilters');
    var similarCount    = document.getElementById('confSimilarCount');
    var loadingEl       = document.getElementById('confLoading');
    var errorEl         = document.getElementById('confError');

    confSelect.addEventListener('change', function () {
        otherWrap.style.display = this.value === 'other' ? '' : 'none';
    });

    var tagDebounce = null;
    tagsInput.addEventListener('input', function () {
        clearTimeout(tagDebounce);
        tagDebounce = setTimeout(renderTagChips, 200);
    });

    function renderTagChips() {
        var raw = tagsInput.value.split(',');
        tagChipsEl.innerHTML = '';
        raw.forEach(function (t) {
            t = t.trim();
            if (!t) return;
            var chip = document.createElement('span');
            chip.className = 'conf-tag-chip';
            chip.textContent = t;
            tagChipsEl.appendChild(chip);
        });
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();

        var title      = document.getElementById('confPaperTitle').value.trim();
        var conference = confSelect.value;
        var year       = document.getElementById('confYear').value;
        var day        = document.getElementById('confDay').value;
        var tags       = tagsInput.value.trim();
        var otherName  = document.getElementById('confOtherName').value.trim();

        if (!title || !conference || !year) return;

        var confLabel = conference === 'other' && otherName
            ? otherName.toUpperCase()
            : (CONF_LABELS[conference] || conference.toUpperCase());

        showLoading();

        var payload = {
            paper_title: title,
            conference: conference,
            year: year,
            day: day || '',
            tags: tags,
            other_conference: otherName
        };

        fetch(SEARCH_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify(payload)
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            hideLoading();

            if (data.error) {
                showError(data.error);
                return;
            }

            renderResults(data, confLabel, year, title);
        })
        .catch(function (err) {
            hideLoading();
            showError('Network error — please try again.');
        });
    });


    function showLoading() {
        resultsArea.style.display = '';
        loadingEl.style.display = 'flex';
        errorEl.style.display = 'none';
        paperCard.style.display = 'none';
        similarSection.style.display = 'none';
        resultHeader.innerHTML = '';
        submitBtn.disabled = true;
        submitBtn.innerHTML =
            '<span class="conf-spinner-sm"></span> Searching\u2026';
    }

    function hideLoading() {
        loadingEl.style.display = 'none';
        submitBtn.disabled = false;
        submitBtn.innerHTML =
            '<svg class="conf-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>' +
            ' Search Conference';
    }

    function showError(msg) {
        errorEl.style.display = 'flex';
        document.getElementById('confErrorMsg').textContent = msg;
        paperCard.style.display = 'none';
        similarSection.style.display = 'none';
    }


    function renderResults(data, confLabel, year, queryTitle) {
        errorEl.style.display = 'none';

        resultHeader.innerHTML =
            '<span class="conf-result-badge">' + escHtml(confLabel) + ' ' + escHtml(year) + '</span>' +
            '<span class="conf-result-query">Results for "<strong>' + escHtml(queryTitle) + '</strong>"</span>';

        var paper = data.paper || null;
        var similar = data.similar || [];

        if (paper) {
            paperCard.style.display = '';
            document.getElementById('confPaperResultTitle').textContent = paper.title || queryTitle;

            setInfoValue('confPaperId',      paper.paper_id);
            setInfoValue('confSession',      paper.session);
            setInfoValue('confRoom',         paper.room);
            setInfoValue('confTimeSlot',     paper.time_slot);
            setInfoValue('confPosterBoard',  paper.poster_board);

            toggleBlock('confPaperIdBlock',      paper.paper_id);
            toggleBlock('confSessionBlock',      paper.session);
            toggleBlock('confRoomBlock',         paper.room);
            toggleBlock('confTimeBlock',         paper.time_slot);
            toggleBlock('confPosterBoardBlock',  paper.poster_board);

            var noteEl = document.getElementById('confNotFoundNote');
            var noteMsg = document.getElementById('confNotFoundMsg');
            if (paper.partial) {
                noteEl.style.display = 'flex';
                noteMsg.textContent = paper.partial_message || 'Some scheduling details could not be retrieved.';
            } else {
                noteEl.style.display = 'none';
            }
        } else {
            paperCard.style.display = '';
            document.getElementById('confPaperResultTitle').textContent = queryTitle;
            setInfoValue('confPaperId',      null);
            setInfoValue('confSession',      null);
            setInfoValue('confRoom',         null);
            setInfoValue('confTimeSlot',     null);
            setInfoValue('confPosterBoard',  null);

            toggleBlock('confPaperIdBlock',     false);
            toggleBlock('confPosterBoardBlock', false);

            var noteEl2 = document.getElementById('confNotFoundNote');
            noteEl2.style.display = 'flex';
            document.getElementById('confNotFoundMsg').textContent =
                'Paper not found in the ' + confLabel + ' ' + year + ' program. Try checking the title or conference year.';
        }

        if (similar.length > 0) {
            renderSimilarPapers(similar);
        } else {
            similarSection.style.display = 'none';
        }

        resultsArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function setInfoValue(elId, value) {
        var el = document.getElementById(elId);
        el.textContent = value || '\u2014';
        el.classList.toggle('conf-info-na', !value);
    }

    function toggleBlock(blockId, value) {
        var block = document.getElementById(blockId);
        if (block) block.style.display = value ? '' : 'none';
    }


    function renderSimilarPapers(papers) {
        similarSection.style.display = '';
        similarCount.textContent = papers.length + ' paper' + (papers.length !== 1 ? 's' : '');

        var allTags = {};
        papers.forEach(function (p) {
            (p.tags || []).forEach(function (t) {
                allTags[t] = (allTags[t] || 0) + 1;
            });
        });

        var tagList = Object.keys(allTags).sort(function (a, b) {
            return allTags[b] - allTags[a];
        });

        similarFilters.innerHTML = '';
        if (tagList.length > 0) {
            var allBtn = document.createElement('button');
            allBtn.type = 'button';
            allBtn.className = 'conf-filter-chip active';
            allBtn.textContent = 'All';
            allBtn.dataset.tag = '';
            allBtn.addEventListener('click', function () { filterSimilar(''); });
            similarFilters.appendChild(allBtn);

            tagList.slice(0, 12).forEach(function (tag) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'conf-filter-chip';
                btn.textContent = tag + ' (' + allTags[tag] + ')';
                btn.dataset.tag = tag;
                btn.addEventListener('click', function () { filterSimilar(tag); });
                similarFilters.appendChild(btn);
            });
        }

        window._confSimilarPapers = papers;
        renderSimilarList(papers);
    }

    function filterSimilar(tag) {
        var chips = similarFilters.querySelectorAll('.conf-filter-chip');
        chips.forEach(function (c) {
            c.classList.toggle('active', c.dataset.tag === tag);
        });

        var papers = window._confSimilarPapers || [];
        if (tag) {
            papers = papers.filter(function (p) {
                return (p.tags || []).indexOf(tag) !== -1;
            });
        }
        renderSimilarList(papers);
        similarCount.textContent = papers.length + ' paper' + (papers.length !== 1 ? 's' : '');
    }

    function renderSimilarList(papers) {
        similarList.innerHTML = '';

        if (papers.length === 0) {
            similarList.innerHTML =
                '<div class="conf-empty-state">No similar papers match this filter.</div>';
            return;
        }

        papers.forEach(function (p) {
            var card = document.createElement('div');
            card.className = 'conf-similar-card';

            var meta = [];
            if (p.session)           meta.push('<span class="conf-sm-session">' + escHtml(p.session) + '</span>');
            if (p.room)              meta.push('<span class="conf-sm-room">' + escHtml(p.room) + '</span>');
            if (p.time_slot)         meta.push('<span class="conf-sm-time">' + escHtml(p.time_slot) + '</span>');

            var tagsHtml = '';
            if (p.tags && p.tags.length) {
                tagsHtml = '<div class="conf-sm-tags">' +
                    p.tags.map(function (t) { return '<span class="conf-sm-tag">' + escHtml(t) + '</span>'; }).join('') +
                    '</div>';
            }

            card.innerHTML =
                '<div class="conf-sm-header">' +
                    '<h4 class="conf-sm-title">' + escHtml(p.title) + '</h4>' +
                    (p.authors ? '<p class="conf-sm-authors">' + escHtml(p.authors) + '</p>' : '') +
                '</div>' +
                (meta.length ? '<div class="conf-sm-meta">' + meta.join('') + '</div>' : '') +
                tagsHtml;

            similarList.appendChild(card);
        });
    }


    function escHtml(str) {
        if (!str) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }
})();
