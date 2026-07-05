function onPendingGroupChange(select) {
    var form = select.closest('form');
    if (!form) return;
    if (select.value) {
        form.setAttribute('action', select.value);
    }
}
document.querySelectorAll('form.pending-form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
        var sel = form.querySelector('select[name="group_select"]');
        if (sel && sel.value) {
            form.setAttribute('action', sel.value);
        } else {
            e.preventDefault();
        }
    });
});
