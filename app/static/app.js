(function () {
    const scrollKey = "restobar:scroll-restore";
    const confirmModal = document.querySelector("[data-confirm-modal]");
    const confirmTitle = document.querySelector("[data-confirm-title]");
    const confirmMessage = document.querySelector("[data-confirm-message]");
    const confirmAccept = document.querySelector("[data-confirm-accept]");
    const confirmCancelButtons = document.querySelectorAll("[data-confirm-cancel]");
    const sidebar = document.querySelector("[data-sidebar]");
    const sidebarBackdrop = document.querySelector("[data-sidebar-backdrop]");

    let pendingConfirmAction = null;

    function currentPathKey() {
        return `${window.location.pathname}${window.location.search}`;
    }

    function storeScrollPosition() {
        sessionStorage.setItem(
            scrollKey,
            JSON.stringify({
                path: currentPathKey(),
                y: window.scrollY || window.pageYOffset || 0,
            })
        );
    }

    function restoreScrollPosition() {
        const raw = sessionStorage.getItem(scrollKey);
        if (!raw) {
            return;
        }

        try {
            const data = JSON.parse(raw);
            if (data.path !== currentPathKey()) {
                return;
            }

            const y = Number(data.y || 0);
            window.requestAnimationFrame(() => {
                window.scrollTo(0, y);
                window.setTimeout(() => window.scrollTo(0, y), 90);
            });
        } catch (error) {
            // Ignore malformed storage values.
        } finally {
            sessionStorage.removeItem(scrollKey);
        }
    }

    function ensureFlashContainer() {
        let container = document.querySelector(".flash-container");
        if (container) {
            return container;
        }

        const contentWrapper = document.querySelector(".content-wrapper");
        if (!contentWrapper) {
            return null;
        }

        container = document.createElement("div");
        container.className = "flash-container";
        contentWrapper.parentNode.insertBefore(container, contentWrapper);
        return container;
    }

    function dismissFlash(node) {
        if (!node) {
            return;
        }
        node.classList.add("is-hiding");
        window.setTimeout(() => node.remove(), 220);
    }

    function scheduleFlashDismiss(node) {
        const timeout = node.classList.contains("flash-error") ? 7000 : 4500;
        window.setTimeout(() => dismissFlash(node), timeout);
    }

    function showLocalFlash(message, category) {
        const container = ensureFlashContainer();
        if (!container) {
            window.alert(message);
            return;
        }

        const icons = {
            success: "fa-circle-check",
            info: "fa-circle-info",
            warning: "fa-triangle-exclamation",
            error: "fa-circle-exclamation",
        };

        const flash = document.createElement("div");
        flash.className = `flash-message flash-${category || "info"} shadow-sm`;
        flash.setAttribute("data-flash", "");
        flash.innerHTML = `
            <div class="flash-icon">
                <i class="fa-solid ${icons[category] || icons.info}"></i>
            </div>
            <div class="flash-copy"></div>
            <button class="flash-close" type="button" data-flash-close aria-label="Cerrar alerta">
                <i class="fa-solid fa-xmark"></i>
            </button>
        `;

        const copy = flash.querySelector(".flash-copy");
        if (copy) {
            copy.textContent = message;
        }

        container.appendChild(flash);
        scheduleFlashDismiss(flash);
    }

    function closeConfirmModal() {
        if (!confirmModal) {
            pendingConfirmAction = null;
            return;
        }

        pendingConfirmAction = null;
        confirmModal.hidden = true;
        document.body.classList.remove("modal-open");
    }

    function openConfirmModal(title, message, onAccept) {
        if (!confirmModal || !confirmTitle || !confirmMessage || !confirmAccept) {
            const fallbackMessage = message || title || "¿Deseas continuar?";
            if (window.confirm(fallbackMessage)) {
                onAccept();
            }
            return;
        }

        pendingConfirmAction = onAccept;
        confirmTitle.textContent = title || "¿Deseas continuar?";
        confirmMessage.textContent = message || "Confirma esta acción para continuar.";
        confirmModal.hidden = false;
        document.body.classList.add("modal-open");
        confirmAccept.focus();
    }

    function submitForm(form) {
        if (!form) {
            return;
        }

        if ((form.method || "get").toLowerCase() === "post") {
            storeScrollPosition();
        }

        HTMLFormElement.prototype.submit.call(form);
    }

    function validateSplitForm(form) {
        const rows = form.querySelectorAll("[data-split-row]");
        for (const row of rows) {
            const total = Number(row.dataset.itemQuantity || 0);
            const itemName = row.dataset.itemName || "el producto";
            const inputs = row.querySelectorAll("[data-split-input]");
            let assigned = 0;

            for (const input of inputs) {
                const value = Number(input.value || 0);
                if (value < 0) {
                    return `No puedes usar cantidades negativas en ${itemName}.`;
                }
                if (value > total) {
                    return `No puedes asignar más de ${total} unidades en ${itemName}.`;
                }
                assigned += value;
            }

            if (assigned !== total) {
                return `Debes repartir exactamente ${total} unidades de ${itemName}.`;
            }
        }

        return null;
    }

    function wireFlashMessages() {
        document.querySelectorAll("[data-flash]").forEach((flash) => {
            if (flash.dataset.dismissWired === "true") {
                return;
            }
            flash.dataset.dismissWired = "true";
            scheduleFlashDismiss(flash);
        });
    }

    function openSidebar() {
        if (!sidebar) {
            return;
        }
        document.body.classList.add("sidebar-open");
        if (sidebarBackdrop) {
            sidebarBackdrop.hidden = false;
        }
    }

    function closeSidebar() {
        if (!sidebar) {
            return;
        }
        document.body.classList.remove("sidebar-open");
        if (sidebarBackdrop) {
            sidebarBackdrop.hidden = true;
        }
    }

    restoreScrollPosition();
    wireFlashMessages();

    document.addEventListener("click", (event) => {
        const closeFlashButton = event.target.closest("[data-flash-close]");
        if (closeFlashButton) {
            dismissFlash(closeFlashButton.closest("[data-flash]"));
            return;
        }

        if (event.target.closest("[data-sidebar-open]")) {
            openSidebar();
            return;
        }

        if (event.target.closest("[data-sidebar-close]") || event.target.closest("[data-sidebar-backdrop]")) {
            closeSidebar();
            return;
        }

        if (event.target.closest(".nav-link") && document.body.classList.contains("sidebar-open")) {
            closeSidebar();
            return;
        }

        const submitter = event.target.closest("button, input[type='submit']");
        if (!submitter || !submitter.hasAttribute("data-confirm-title")) {
            return;
        }

        const form = submitter.form;
        if (!form) {
            return;
        }

        event.preventDefault();
        openConfirmModal(
            submitter.getAttribute("data-confirm-title"),
            submitter.getAttribute("data-confirm-message"),
            () => submitForm(form)
        );
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        if (form.hasAttribute("data-split-form")) {
            const validationError = validateSplitForm(form);
            if (validationError) {
                event.preventDefault();
                showLocalFlash(validationError, "error");
                return;
            }
        }

        const title = form.getAttribute("data-confirm-title");
        if (title) {
            event.preventDefault();
            openConfirmModal(title, form.getAttribute("data-confirm-message"), () => submitForm(form));
            return;
        }

        if ((form.method || "get").toLowerCase() === "post") {
            storeScrollPosition();
        }
    });

    if (confirmAccept) {
        confirmAccept.addEventListener("click", () => {
            const action = pendingConfirmAction;
            closeConfirmModal();
            if (action) {
                action();
            }
        });
    }

    confirmCancelButtons.forEach((button) => {
        button.addEventListener("click", closeConfirmModal);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeConfirmModal();
            closeSidebar();
        }
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 1024) {
            closeSidebar();
        }
    });

    document.querySelectorAll(".toggle-password").forEach((button) => {
        button.addEventListener("click", () => {
            const field = button.parentElement?.querySelector("input");
            if (!field) {
                return;
            }

            const nextType = field.type === "password" ? "text" : "password";
            field.type = nextType;
            const icon = button.querySelector("i");
            if (icon) {
                icon.className = `fa-regular ${nextType === "password" ? "fa-eye" : "fa-eye-slash"}`;
            }
        });
    });

    const splitSelector = document.querySelector("[data-split-selector]");
    if (splitSelector) {
        splitSelector.addEventListener("change", () => {
            const orderUrl = splitSelector.getAttribute("data-order-url");
            if (!orderUrl) {
                return;
            }

            const nextUrl = new URL(orderUrl, window.location.origin);
            nextUrl.searchParams.set("personas", splitSelector.value);
            window.location.assign(nextUrl.toString());
        });
    }
})();
