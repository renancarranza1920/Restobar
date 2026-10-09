(() => {
    const catalogue = document.querySelector('[data-menu-catalogue]');
    if (!catalogue) return;

    const cards = [...catalogue.querySelectorAll('[data-menu-product]')];
    const categoryButtons = [...catalogue.querySelectorAll('[data-menu-category-filter]')];
    const statusSelect = catalogue.querySelector('[data-menu-status-filter]');
    const results = catalogue.querySelector('[data-menu-results]');
    const empty = catalogue.querySelector('[data-menu-empty]');
    let category = '';

    const filterProducts = () => {
        const status = statusSelect ? statusSelect.value : '';
        let visible = 0;
        cards.forEach(card => {
            const matches = (!category || card.dataset.menuCategory === category)
                && (!status || card.dataset.menuStatus === status);
            card.hidden = !matches;
            if (matches) visible += 1;
        });
        if (results) results.textContent = `${visible} producto${visible === 1 ? '' : 's'}`;
        if (empty) empty.hidden = visible > 0;
        categoryButtons.forEach(button => {
            const active = button.dataset.menuCategoryFilter === category;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', String(active));
        });
    };

    categoryButtons.forEach(button => button.addEventListener('click', () => {
        category = button.dataset.menuCategoryFilter;
        filterProducts();
    }));
    if (statusSelect) statusSelect.addEventListener('change', filterProducts);
    const reset = catalogue.querySelector('[data-menu-reset]');
    if (reset) reset.addEventListener('click', () => {
        category = '';
        if (statusSelect) statusSelect.value = '';
        filterProducts();
        categoryButtons[0]?.focus();
    });
    const controls = catalogue.querySelector('[data-menu-controls]');
    if (controls) controls.hidden = false;

    catalogue.querySelectorAll('[data-menu-product-image]').forEach(image => {
        const showFallback = () => {
            const fallback = image.dataset.menuFallback;
            if (!fallback || image.getAttribute('src') === fallback) return;
            image.src = fallback;
            image.alt = '';
            const media = image.closest('.menu-product-media');
            media?.classList.add('menu-product-illustration');
            const label = media?.querySelector('.menu-illustration-label');
            if (label) label.hidden = false;
        };
        image.addEventListener('error', showFallback);
        if (image.complete && image.naturalWidth === 0) showFallback();
    });
})();
