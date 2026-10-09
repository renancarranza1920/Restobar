(() => {
    'use strict';
    const readJSON = id => JSON.parse(document.getElementById(id)?.textContent || '{}');
    const geography = readJSON('fiscal-geography-data');
    const activities = readJSON('fiscal-activity-data');
    const fill = (select, options, placeholder) => {
        select.replaceChildren(new Option(placeholder, ''));
        for (const option of options || []) select.add(new Option(option.label, option.code));
    };
    document.querySelectorAll('[data-fiscal-address]').forEach(group => {
        const department = group.querySelector('[data-fiscal-department]');
        department.addEventListener('change', () => {
            fill(group.querySelector('[data-fiscal-municipality]'), geography.municipalities?.[department.value], 'Selecciona un municipio');
            fill(group.querySelector('[data-fiscal-district]'), geography.districts?.[department.value], 'Selecciona tu distrito');
        });
    });
    document.querySelectorAll('[data-activity-input]').forEach(input => {
        input.addEventListener('change', () => {
            const option = activities.find(option => option.code === input.value.trim());
            const description = input.closest('.billing-form-grid').querySelector('[data-activity-description]');
            if (option && description) description.value = option.label;
        });
    });
    const documentType = document.querySelector('[data-document-type]');
    if (documentType) documentType.addEventListener('change', () => {
        const isCCF = documentType.value === '03';
        document.querySelectorAll('[data-type-fields]').forEach(fields => {
            fields.hidden = fields.dataset.typeFields !== documentType.value;
            fields.disabled = fields.hidden;
        });
        const address = document.querySelector('[data-buyer-address]');
        if (isCCF) address.open = true;
        address.querySelectorAll('input,select').forEach(input => { input.required = isCCF; });
        address.querySelector('[data-address-qualifier]').textContent = isCCF ? '(obligatoria para CCF)' : '(opcional para Factura)';
    });
})();
