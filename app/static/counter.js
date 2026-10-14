(() => {
    const root = document.querySelector('[data-counter]');
    if (!root) return;
    const $ = selector => root.querySelector(selector);
    const cents = value => Math.round(Number(value || 0) * 100);
    const currency = value => new Intl.NumberFormat('es-SV', {style:'currency', currency:'USD'}).format(value / 100);
    const products = new Map([...root.querySelectorAll('[data-product-id]')].map(button => [Number(button.dataset.productId), {
        id:Number(button.dataset.productId), name:button.dataset.name, price:cents(button.dataset.price),
        available:button.dataset.available === '' ? null : Number(button.dataset.available), button
    }]));
    let cart = new Map(), key = root.dataset.key, busy = false, uncertain = false, category = '', currentShift = Number(root.dataset.shift);
    const total = () => [...cart.values()].reduce((sum, row) => sum + row.price * row.quantity, 0);
    const error = message => { $('[data-sale-error]').textContent = message; $('[data-sale-error]').hidden = !message; };
    function payment() {
        const amount = total(), cash = $('input[name=method]:checked').value === 'efectivo';
        const received = cents($('[data-received]').value);
        $('[data-total]').textContent = currency(amount);
        $('[data-change]').textContent = currency(Math.max(0, received - amount));
        $('[data-cash-fields]').hidden = !cash;
        $('[data-open-cart]').hidden = !cart.size;
        $('[data-open-cart]').textContent = `${[...cart.values()].reduce((n, r) => n + r.quantity, 0)} productos · ${currency(amount)} · Ver cobro ↓`;
        $('[data-checkout-button]').textContent = busy ? 'Confirmando cobro…' : uncertain ? 'Reintentar el mismo cobro' : `Cobrar ${currency(amount)}`;
        $('[data-checkout-button]').disabled = busy || (!uncertain && (!amount || !currentShift || (cash && received < amount)));
    }
    function renderCart() {
        const list = $('[data-cart-lines]'); list.replaceChildren();
        if (!cart.size) {
            const empty = document.createElement('p'); empty.className = 'counter-empty'; empty.textContent = 'Toca un producto para empezar.'; list.append(empty);
        }
        for (const row of cart.values()) {
            const line = document.createElement('div'); line.className = 'counter-line';
            const title = document.createElement('strong'); title.textContent = row.name;
            const subtotal = document.createElement('b'); subtotal.textContent = currency(row.price * row.quantity);
            const head = document.createElement('div'); head.className = 'counter-line-head'; head.append(title, subtotal);
            const qty = document.createElement('div'); qty.className = 'counter-quantity';
            for (const [label, delta, aria] of [['−', -1, 'Quitar una unidad'], [String(row.quantity), 0, 'Cantidad'], ['+', 1, 'Añadir una unidad']]) {
                const control = document.createElement(delta ? 'button' : 'span'); control.textContent = label;
                if (delta) {
                    control.type = 'button'; control.setAttribute('aria-label', `${aria} de ${row.name}`);
                    control.disabled = busy || uncertain;
                    control.addEventListener('click', () => change(row.id, delta));
                }
                qty.append(control);
            }
            const details = document.createElement('details'); details.className = 'counter-line-notes';
            const summary = document.createElement('summary'); summary.textContent = row.notes ? 'Indicaciones añadidas' : 'Indicaciones a cocina';
            const note = document.createElement('input'); note.maxLength = 200; note.placeholder = 'Ej. Sin cebolla'; note.value = row.notes || '';
            note.setAttribute('aria-label', `Indicaciones para ${row.name}`);
            note.addEventListener('input', () => { row.notes = note.value; summary.textContent = row.notes ? 'Indicaciones añadidas' : 'Indicaciones a cocina'; });
            details.append(summary, note); line.append(head, qty, details); list.append(line);
        }
        payment();
    }
    function change(id, delta) {
        if (busy || uncertain) return;
        const product = products.get(id), existing = cart.get(id), quantity = (existing?.quantity || 0) + delta;
        if (product.available !== null && quantity > product.available) { error(`Solo quedan ${product.available} de ${product.name}.`); return; }
        if (quantity > 999) return;
        if (quantity <= 0) cart.delete(id); else cart.set(id, {...product, ...existing, quantity});
        error(''); renderCart();
    }
    function filter() {
        const query = $('[data-product-search]').value.trim().toLocaleLowerCase(); let visible = 0;
        for (const p of products.values()) {
            const show = (!category || category === p.button.dataset.categoryName) && `${p.name} ${p.button.dataset.categoryName}`.toLocaleLowerCase().includes(query);
            p.button.hidden = !show; if (show) visible++;
        }
        $('[data-search-empty]').hidden = visible > 0;
    }
    for (const p of products.values()) p.button.addEventListener('click', () => change(p.id, 1));
    $('[data-product-search]').addEventListener('input', filter);
    root.querySelectorAll('[data-category]').forEach(button => button.addEventListener('click', () => {
        category = button.dataset.category;
        root.querySelectorAll('[data-category]').forEach(b => b.classList.toggle('is-selected', b === button)); filter();
    }));
    $('[data-clear-cart]').addEventListener('click', () => { if (!busy && !uncertain) { cart.clear(); error(''); renderCart(); } });
    $('[data-received]').addEventListener('input', payment);
    root.querySelectorAll('input[name=method]').forEach(radio => radio.addEventListener('change', payment));
    $('[data-exact]').addEventListener('click', () => { $('[data-received]').value = (total() / 100).toFixed(2); payment(); });
    $('[data-open-cart]').addEventListener('click', () => {
        document.querySelector('#counter-payment').scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'start'});
    });
    function freeze() {
        $('[data-cart-fields]').disabled = busy || uncertain;
        $('[data-clear-cart]').disabled = busy || uncertain;
        for (const p of products.values()) p.button.disabled = busy || uncertain || p.available === 0;
    }
    async function refresh() {
        try {
            const response = await fetch(root.dataset.statusUrl, {headers:{Accept:'application/json'}});
            if (!response.ok || response.redirected) return;
            const result = await response.json();
            $('[data-recent-sales]').innerHTML = result.html;
            currentShift = result.shift_id;
            for (const [id, available] of Object.entries(result.stocks)) {
                const p = products.get(Number(id)); if (!p) continue;
                p.available = available;
                if (available !== null) p.button.querySelector('[data-product-stock]').textContent = `${available} disponibles`;
            }
            freeze(); payment();
        } catch { /* Keep the current order while the connection recovers. */ }
    }
    $('[data-checkout-button]').addEventListener('click', async () => {
        if (busy || !cart.size) return;
        busy = true; error(''); freeze(); payment();
        try {
            const response = await fetch(root.dataset.checkout, {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':root.dataset.csrf},
                body:JSON.stringify({key, shift_id:Number(root.dataset.shift), channel:$('input[name=channel]:checked').value,
                    customer:$('[data-customer]').value, method:$('input[name=method]:checked').value,
                    received:$('[data-received]').value,
                    lines:[...cart.values()].map(r => ({id:r.id, price:(r.price / 100).toFixed(2), quantity:r.quantity, notes:r.notes}))})});
            if (response.redirected) throw new Error('Sesión vencida. Recarga y revisa el historial antes de continuar.');
            const result = await response.json();
            if (!response.ok) {
                uncertain = response.status >= 409; error(result.error); return;
            }
            uncertain = false; key = result.key; cart.clear();
            $('[data-received]').value = ''; $('[data-customer]').value = '';
            $('[data-success-title]').textContent = `Pedido #${result.order_id} cobrado · ${currency(cents(result.total))}`;
            $('[data-success-copy]').textContent = `${result.kitchen ? 'Enviado a cocina.' : 'Listo para entregar.'} Cambio: ${currency(cents(result.change))}${result.replay ? ' · Cobro anterior confirmado, sin duplicar.' : ''}`;
            $('[data-ticket]').href = result.ticket_url;
            $('[data-billing]').hidden = !result.billing_url;
            if (result.billing_url) $('[data-billing]').href = result.billing_url;
            $('[data-sale-success]').hidden = false;
            renderCart(); await refresh();
        } catch (err) {
            uncertain = true; error('No se confirmó la respuesta. Reintenta el mismo cobro para comprobarlo sin duplicar la venta.');
        } finally { busy = false; freeze(); payment(); }
    });
    payment(); setInterval(() => { if (!busy && !document.hidden) refresh(); }, 5000);
})();
