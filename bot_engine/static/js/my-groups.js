function makePrimary(groupId, btn) {
    btn.disabled = true;
    const originalLabel = btn.innerHTML;
    btn.innerHTML = '…';
    fetch('/api/set-my-primary-group/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'X-CSRFToken': getCSRFToken(),
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ group_id: groupId }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                window.location.reload();
            } else {
                btn.disabled = false;
                btn.innerHTML = originalLabel;
                showToast(data.error || 'Error updating primary group', 'error');
            }
        })
        .catch(() => {
            btn.disabled = false;
            btn.innerHTML = originalLabel;
            showToast('Network error', 'error');
        });
}
