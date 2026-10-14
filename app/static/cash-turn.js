const closeForm = document.querySelector('[data-turn-close]');
if (closeForm) {
    const count = closeForm.querySelector('[data-counted]');
    const note = closeForm.querySelector('[data-close-note]');
    count.addEventListener('input', () => {
        const diff = Math.round(Number(count.value) * 100) - Math.round(Number(closeForm.dataset.expected) * 100);
        closeForm.querySelector('[data-difference]').textContent = count.value === '' ? '—' : new Intl.NumberFormat('es-SV', {style:'currency', currency:'USD'}).format(diff / 100);
        note.required = diff !== 0;
    });
}
