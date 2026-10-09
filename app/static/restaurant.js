/* Original local SVG icon set and restaurant interaction layer. No CDN required. */
(function () {
    "use strict";
    const drawings = {
        home: '<path d="m3 10 9-7 9 7v10H3V10Z"/><path d="M9 20v-7h6v7"/>',
        menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
        close: '<path d="m6 6 12 12M18 6 6 18"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        minus: '<path d="M5 12h14"/>',
        check: '<path d="m5 12 4 4L19 6"/>',
        checks: '<path d="m2 12 4 4L16 6m-5 9 3 3 8-10"/>',
        circle: '<circle cx="12" cy="12" r="8"/>',
        dot: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/>',
        solidDot: '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
        checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
        crossCircle: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
        info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
        warning: '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v.1"/>',
        danger: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4v.1"/>',
        left: '<path d="m15 5-7 7 7 7"/>',
        right: '<path d="m9 5 7 7-7 7"/>',
        up: '<path d="m5 15 7-7 7 7"/>',
        down: '<path d="m5 9 7 7 7-7"/>',
        arrowRight: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
        arrowLeft: '<path d="M20 12H4m6-6-6 6 6 6"/>',
        arrowUp: '<path d="M12 20V4m-6 6 6-6 6 6"/>',
        arrowDown: '<path d="M12 4v16m-6-6 6 6 6-6"/>',
        exchange: '<path d="M3 7h17m-4-4 4 4-4 4M21 17H4m4-4-4 4 4 4"/>',
        search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
        receipt: '<path d="M5 3h14v18l-3-2-4 2-4-2-3 2V3Z"/><path d="M8 7h8M8 11h8M8 15h4"/>',
        document: '<path d="M5 3h9l5 5v13H5V3Z"/><path d="M14 3v6h5M8 13h8M8 17h5"/>',
        chair: '<path d="M6 12V4h12v8M4 12h16v5H4v-5Zm2 5v4m12-4v4M8 7h8"/>',
        utensils: '<path d="M5 3v6c0 4 6 4 6 0V3M8 3v18M18 3c-4 5-4 10 0 10V3Zm0 10v8"/>',
        cloche: '<path d="M3 17h18M5 14a7 7 0 0 1 14 0H5Zm7-7V4m-2-1h4M7 21h10"/>',
        fire: '<path d="M12 2c2 6 7 7 7 13a7 7 0 1 1-14 0c0-3 1-6 4-8 0 4 2 4 2 4s3-4 1-9Z"/><path d="M12 13c3 3 4 5 0 8-4-2-3-6 0-8Z"/>',
        drink: '<path d="m3 5 9 10 9-10H3Zm9 10v6m-5 0h10M17 6l3-4"/>',
        store: '<path d="M4 10v11h16V10M3 4h18l1 6a3 3 0 0 1-6 0 4 4 0 0 1-8 0 3 3 0 0 1-6 0l1-6ZM9 21v-7h6v7"/>',
        layer: '<path d="m12 3 10 5-10 5L2 8l10-5Zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',
        box: '<path d="m12 3 9 5v9l-9 5-9-5V8l9-5ZM3 8l9 5 9-5m-9 5v9M8 5l9 5"/>',
        boxes: '<path d="m12 2 5 3v5l-5 3-5-3V5l5-3ZM2 13l5-3 5 3v6l-5 3-5-3v-6Zm10 0 5-3 5 3v6l-5 3-5-3"/>',
        warehouse: '<path d="m3 7 9-4 9 4v14H3V7Z"/><path d="M7 21V10h10v11M7 14h10M7 18h10"/>',
        calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18M7 14h2m6 0h2M7 17h2"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
        history: '<path d="M3 10a9 9 0 1 1 1 8M3 4v6h6M12 7v5l4 2"/>',
        wallet: '<path d="M4 5h15v4M4 5a2 2 0 0 0 0 4h17v12H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2ZM21 13h-6v4h6"/>',
        cash: '<path d="M5 3h14v7H5V3Zm-2 9h18v9H3v-9ZM8 6h8M7 17h4m5-2v3"/>',
        money: '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M5 9v6m14-6v6"/>',
        card: '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M2 9h20M6 15h4"/>',
        dollar: '<path d="M12 2v20m5-16c-7-5-14 3-6 6 9 3 2 11-6 6"/>',
        chart: '<path d="M3 3v18h18M7 16v-5m5 5V7m5 9V4"/>',
        trend: '<path d="M3 21V3m0 18h18M6 15l5-6 4 3 6-8m-6 0h6v6"/>',
        pie: '<path d="M12 3a9 9 0 1 0 9 9h-9V3Zm4-1v6h6a7 7 0 0 0-6-6Z"/>',
        users: '<circle cx="9" cy="7" r="3"/><path d="M2 21v-3a7 7 0 0 1 14 0v3M16 4a3 3 0 0 1 0 6m2 4a6 6 0 0 1 4 7"/>',
        user: '<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
        userPlus: '<circle cx="9" cy="7" r="3"/><path d="M2 21v-3a7 7 0 0 1 12-5m4-2v8m-4-4h8"/>',
        shield: '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4Z"/><path d="m8 12 3 3 5-6"/>',
        key: '<circle cx="8" cy="8" r="5"/><path d="m12 12 9 9m-5-5 3-3m0 6 3-3"/>',
        lock: '<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M7 10V7a5 5 0 0 1 10 0v3m-5 5v3"/>',
        unlock: '<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M7 10V7a5 5 0 0 1 9-3m-4 11v3"/>',
        exit: '<path d="M10 3H3v18h7m-2-9h14m-5-5 5 5-5 5"/>',
        eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
        eyeSlash: '<path d="m3 3 18 18M9 5a11 11 0 0 1 13 7 18 18 0 0 1-4 5M6 6a18 18 0 0 0-4 6s4 7 10 7a11 11 0 0 0 4-1"/>',
        moon: '<path d="M20 15A9 9 0 0 1 9 3a9 9 0 1 0 11 12Z"/>',
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
        bell: '<path d="M5 17h14l-2-4V9a5 5 0 0 0-10 0v4l-2 4Zm5 4h4"/>',
        filter: '<path d="M3 4h18l-7 9v7l-4 2v-9L3 4Z"/>',
        sliders: '<path d="M4 7h16M4 17h16M9 4v6m6 4v6"/>',
        tag: '<path d="M3 3h9l9 9-9 9-9-9V3Z"/><circle cx="8" cy="8" r="1.5"/>',
        clipboard: '<path d="M8 5H4v17h16V5h-4M8 3h8v5H8V3Zm0 10h8m-8 4h6"/>',
        listCheck: '<path d="m2 7 2 2 3-4m-5 12 2 2 3-4M11 7h11M11 17h11"/>',
        image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="2"/><path d="m3 17 6-5 4 4 4-6 4 5"/>',
        edit: '<path d="m15 3 6 6-12 12H3v-6L15 3Zm-3 3 6 6"/>',
        trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
        save: '<path d="M3 3h15l3 3v15H3V3Zm4 0v7h10V3M7 21v-7h10v7"/>',
        print: '<path d="M6 8V3h12v5M6 17H3V8h18v9h-3M6 14h12v7H6v-7Zm12-3v.1"/>',
        refresh: '<path d="M3 10a9 9 0 0 1 16-5l2 3m0-6v6h-6M21 14a9 9 0 0 1-16 5l-2-3m0 6v-6h6"/>',
        link: '<path d="m9 15 6-6M8 10 5 13a4 4 0 0 0 6 6l3-3m-4-8 3-3a4 4 0 0 1 6 6l-3 3"/>',
        ban: '<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>',
        broom: '<path d="m18 2-6 11m0-2 7 4-5 7H3l3-10 6-1ZM7 16l-2 6m6-4-1 4"/>',
        bag: '<path d="M4 7h16l1 15H3L4 7Zm4 0V5a4 4 0 0 1 8 0v2m-8 5v.1m8-.1v.1"/>',
        basket: '<path d="m8 3-4 7m12-7 4 7M2 10h20l-3 11H5L2 10Zm6 4 1 4m7-4-1 4"/>',
        cart: '<path d="M2 3h3l3 13h11l3-10H6m4 3h8m-4-3v6"/><circle cx="10" cy="21" r="1"/><circle cx="18" cy="21" r="1"/>',
        inbox: '<path d="M6 3h12l4 11v7H2v-7L6 3ZM2 14h6l2 3h4l2-3h6"/>',
        palette: '<path d="M12 3a9 9 0 1 0 0 18c5 0 0-5 4-5h2c5 0 4-13-6-13Z"/><circle cx="7" cy="10" r="1"/><circle cx="11" cy="7" r="1"/><circle cx="16" cy="9" r="1"/>',
        grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        map: '<path d="m2 5 7-3 6 3 7-3v17l-7 3-6-3-7 3V5Zm7-3v17m6-14v17"/>',
        badge: '<rect x="4" y="4" width="16" height="18" rx="2"/><path d="M9 4V2h6v2M8 17h8"/><circle cx="12" cy="11" r="3"/>',
        calculator: '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M8 6h8M8 11h1m6 0h1m-8 4h1m6 0h1m-8 4h1m6 0h1"/>',
        star: '<path d="m12 2 3 7 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-7Z"/>',
        heart: '<path d="M12 21 3 12C-3 4 8-2 12 6c4-8 15-2 9 6l-9 9Z"/>',
        upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
        download: '<path d="M12 3v13m-5-5 5 5 5-5M4 15v6h16v-6"/>',
        external: '<path d="M13 3h8v8m0-8L10 14M9 3H3v18h18v-6"/>',
        book: '<path d="M12 5v16M3 3l9 2 9-2v16l-9 2-9-2V3Z"/>',
        pause: '<circle cx="12" cy="12" r="9"/><path d="M9 8v8m6-8v8"/>',
        truck: '<path d="M2 4h13v14H2V4Zm13 5h4l3 4v5h-7"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="19" r="2"/>',
        note: '<path d="M3 3h18v12l-6 6H3V3Zm12 18v-6h6M7 7h10M7 11h7"/>',
        soap: '<rect x="3" y="9" width="18" height="12" rx="4"/><circle cx="6" cy="4" r="2"/><circle cx="14" cy="5" r="3"/><path d="M8 14h8"/>'
    };
    const icons = {};
    const aliases = {
        home: "house", menu: "bars", close: "xmark", plus: "plus plus-circle", minus: "minus", check: "check", checks: "check-double",
        dot: "circle-dot", solidDot: "circle", checkCircle: "circle-check check-circle", crossCircle: "circle-xmark", info: "circle-info", warning: "triangle-exclamation", danger: "circle-exclamation",
        left: "chevron-left", right: "chevron-right", up: "chevron-up", down: "chevron-down", arrowRight: "arrow-right", arrowLeft: "arrow-left", arrowUp: "arrow-up", arrowDown: "arrow-down", exchange: "arrow-right-arrow-left",
        search: "magnifying-glass search", receipt: "receipt file-invoice-dollar file-invoice", document: "file-pdf", chair: "chair", utensils: "utensils", cloche: "bell-concierge", fire: "fire-burner", drink: "martini-glass-citrus",
        store: "store", layer: "layer-group", box: "box cube box-open", boxes: "boxes-stacked", warehouse: "warehouse", calendar: "calendar calendar-days calendar-range calendar-day", clock: "clock", history: "clock-rotate-left",
        wallet: "wallet", cash: "cash-register", money: "money-bill-wave", card: "credit-card", dollar: "sack-dollar", chart: "chart-column", trend: "chart-line arrow-trend-up", pie: "chart-pie",
        users: "users user-group users-gear", user: "user user-gear user-slash", userPlus: "user-plus", shield: "shield-halved user-shield", key: "key", lock: "lock", unlock: "lock-open", exit: "right-from-bracket arrow-right-from-bracket", eye: "eye", eyeSlash: "eye-slash", moon: "moon", sun: "sun", bell: "bell",
        filter: "filter", sliders: "sliders", tag: "tag tags", clipboard: "clipboard-list clipboard-check", listCheck: "list-check", image: "image", edit: "pen pen-ruler", trash: "trash trash-can", save: "save floppy-disk", print: "print", refresh: "arrows-rotate rotate rotate-right", link: "link", ban: "ban link-slash", broom: "broom broom-ball eraser", bag: "bag-shopping", basket: "basket-shopping", cart: "cart-plus", inbox: "inbox", palette: "palette", grid: "grip", map: "map-location-dot", badge: "id-badge address-card", calculator: "calculator", star: "ranking-star star", heart: "heart hand-holding-heart", upload: "arrow-up-from-bracket", download: "download", external: "arrow-up-right-from-square", book: "book-open", pause: "circle-pause", truck: "truck-ramp-box", note: "note-sticky", soap: "soap"
    };
    Object.entries(aliases).forEach(([drawing, names]) => names.split(" ").forEach((name) => { icons[`fa-${name}`] = drawings[drawing]; }));
    function renderIcon(node) {
        const name = [...node.classList].find((className) => icons[className]) || "fa-circle-dot";
        if (node.dataset.localIcon === name && node.firstElementChild?.tagName.toLowerCase() === "svg") return;
        node.dataset.localIcon = name;
        node.setAttribute("aria-hidden", "true");
        node.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" focusable="false" aria-hidden="true">${icons[name]}</svg>`;
    }
    function renderIcons(root) {
        if (root.matches?.("i.fa-solid, i.fa-regular")) renderIcon(root);
        root.querySelectorAll?.("i.fa-solid, i.fa-regular").forEach(renderIcon);
    }
    renderIcons(document);
    new MutationObserver((records) => {
        records.forEach((record) => {
            if (record.type === "attributes" && record.target.matches("i.fa-solid, i.fa-regular")) renderIcon(record.target);
            record.addedNodes.forEach((node) => { if (node.nodeType === 1) renderIcons(node); });
        });
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });

    const command = document.querySelector("[data-command-dialog]");
    const commandInput = command?.querySelector("[data-command-input]");
    const commandResults = [...(command?.querySelectorAll("[data-command-result]") || [])];
    let commandIndex = 0;
    let commandReturnFocus = null;
    const normalize = (value) => value.toLocaleLowerCase("es").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    function visibleResults() { return commandResults.filter((node) => !node.hidden); }
    function highlightCommand(index) {
        const results = visibleResults();
        commandIndex = results.length ? (index + results.length) % results.length : 0;
        commandResults.forEach((node) => node.classList.remove("is-highlighted"));
        results[commandIndex]?.classList.add("is-highlighted");
        results[commandIndex]?.scrollIntoView({ block: "nearest" });
    }
    function filterCommand() {
        const term = normalize(commandInput.value.trim());
        commandResults.forEach((node) => { node.hidden = !normalize(node.textContent).includes(term); });
        command.querySelector("[data-command-empty]").hidden = visibleResults().length > 0;
        highlightCommand(0);
    }
    function openCommand() {
        if (!command || command.open) return;
        commandReturnFocus = document.activeElement;
        commandInput.value = "";
        filterCommand();
        command.showModal();
        commandInput.focus();
    }
    function closeCommand() { command?.close(); }
    document.querySelectorAll("[data-command-open]").forEach((node) => node.addEventListener("click", openCommand));
    command?.querySelector("[data-command-close]").addEventListener("click", closeCommand);
    commandInput?.addEventListener("input", filterCommand);
    command?.addEventListener("close", () => commandReturnFocus?.focus());
    command?.addEventListener("click", (event) => {
        if (event.target !== command) return;
        const rect = command.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeCommand();
    });
    document.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && command) { event.preventDefault(); openCommand(); return; }
        if (!command?.open) return;
        if (event.key === "Escape") { event.preventDefault(); closeCommand(); return; }
        if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); highlightCommand(commandIndex + (event.key === "ArrowDown" ? 1 : -1)); }
        if (event.key === "Enter" && event.target === commandInput) { event.preventDefault(); const link = visibleResults()[commandIndex]; if (link) window.location.assign(link.href); }
    });

    /* Mirror existing sidebar hooks, with correct focus and mobile accessibility. */
    const sidebar = document.querySelector("[data-sidebar]");
    const sidebarToggle = document.querySelector("[data-sidebar-open]");
    const main = document.querySelector(".filament-main");
    let sidebarWasOpen = false;
    function syncSidebarAccess() {
        if (!sidebar) return;
        const mobile = window.matchMedia("(max-width: 1024px)").matches;
        const isOpen = mobile && document.body.classList.contains("sidebar-open");
        sidebarToggle?.setAttribute("aria-expanded", String(isOpen));
        sidebar.inert = mobile && !isOpen;
        if (main) main.inert = isOpen;
        if (isOpen && !sidebarWasOpen) sidebar.querySelector("[data-sidebar-close]")?.focus();
        if (!isOpen && sidebarWasOpen) sidebarToggle?.focus();
        sidebarWasOpen = isOpen;
    }
    new MutationObserver(syncSidebarAccess).observe(document.body, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", syncSidebarAccess);
    syncSidebarAccess();
    document.addEventListener("keydown", (event) => {
        if (!sidebarWasOpen) return;
        if (event.key === "Escape") { sidebar.querySelector("[data-sidebar-close]")?.click(); return; }
        if (event.key !== "Tab") return;
        const focusable = [...sidebar.querySelectorAll('a[href], button, input, select, textarea')].filter((node) => !node.disabled && node.getClientRects().length);
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });

    const flashContainer = document.querySelector(".flash-container");
    function announceFlashes(root) {
        if (root.matches?.(".flash-container")) { root.setAttribute("aria-live", "polite"); root.setAttribute("aria-relevant", "additions text"); }
        const nodes = root.matches?.("[data-flash]") ? [root] : root.querySelectorAll?.("[data-flash]") || [];
        nodes.forEach((node) => node.setAttribute("role", node.classList.contains("flash-error") ? "alert" : "status"));
    }
    if (flashContainer) announceFlashes(flashContainer);
    new MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach((node) => { if (node.nodeType === 1) announceFlashes(node); }))).observe(main || document.body, { childList: true, subtree: true });

    /* Real service alerts are supplied by a permission-scoped local API. */
    const alertsToggle = document.querySelector("[data-alerts-open]");
    const alertsPanel = document.querySelector("[data-alerts-panel]");
    const alertsList = document.querySelector("[data-alerts-list]");
    const alertsStatus = document.querySelector("[data-alerts-status]");
    const alertsCount = document.querySelector("[data-alerts-count]");
    let alertsLoading = false;
    function toggleAlerts(open) {
        if (!alertsPanel) return;
        alertsPanel.hidden = !open;
        alertsToggle.setAttribute("aria-expanded", String(open));
        if (open) refreshAlerts();
    }
    async function refreshAlerts() {
        if (!alertsPanel || alertsLoading || !document.body.dataset.alertsUrl) return;
        alertsLoading = true;
        alertsStatus.textContent = "Actualizando el servicio…";
        alertsStatus.hidden = false;
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 12000);
        try {
            const response = await fetch(document.body.dataset.alertsUrl, { headers: { Accept: "application/json" }, credentials: "same-origin", signal: controller.signal });
            if (!response.ok) throw new Error("alerts-unavailable");
            const payload = await response.json();
            if (!Array.isArray(payload.alerts)) throw new Error("alerts-invalid");
            alertsList.replaceChildren();
            payload.alerts.forEach((alert) => {
                const url = new URL(alert.url, window.location.origin);
                if (url.origin !== window.location.origin) return;
                const link = document.createElement("a");
                link.className = "restaurant-service-alert";
                link.href = url.href;
                const icon = document.createElement("i");
                icon.className = `fa-solid ${{ kitchen: "fa-bell-concierge", stock: "fa-boxes-stacked", cash: "fa-cash-register" }[alert.kind] || "fa-circle-info"}`;
                const copy = document.createElement("span");
                const title = document.createElement("strong");
                title.textContent = alert.title;
                const description = document.createElement("small");
                description.textContent = alert.message;
                copy.append(title, description);
                link.append(icon, copy);
                alertsList.append(link);
            });
            const total = payload.alerts.reduce((sum, alert) => sum + Math.max(0, Number(alert.count) || 0), 0);
            alertsCount.hidden = total === 0;
            alertsCount.textContent = total > 99 ? "99+" : String(total);
            alertsToggle.setAttribute("aria-label", total ? `Notificaciones del servicio: ${total} pendientes` : "Notificaciones del servicio");
            alertsStatus.textContent = "Todo al día. No hay alertas pendientes.";
            alertsStatus.hidden = payload.alerts.length > 0;
        } catch (error) {
            alertsStatus.textContent = "No pudimos actualizar las alertas. Usa el botón de actualizar para intentar de nuevo.";
            alertsStatus.hidden = false;
        } finally { alertsLoading = false; window.clearTimeout(timeout); }
    }
    alertsToggle?.addEventListener("click", () => toggleAlerts(alertsPanel.hidden));
    document.querySelector("[data-alerts-refresh]")?.addEventListener("click", refreshAlerts);
    document.addEventListener("click", (event) => { if (alertsPanel && !alertsPanel.hidden && !event.target.closest(".restaurant-notifications")) toggleAlerts(false); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && alertsPanel && !alertsPanel.hidden) { toggleAlerts(false); alertsToggle.focus(); } });
    window.setInterval(() => { if (!document.hidden && alertsPanel && !alertsPanel.hidden) refreshAlerts(); }, 60000);
    if (alertsPanel) refreshAlerts();
})();
