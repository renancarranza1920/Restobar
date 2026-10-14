document.querySelectorAll('[data-recipe-form]').forEach(form => {
    form.querySelector('[data-add-ingredient]')?.addEventListener('click', () => {
        form.querySelector('[data-recipe-rows]').append(document.querySelector('#recipe-row-template').content.cloneNode(true));
    });
    form.addEventListener('click', e => { if (e.target.closest('[data-remove-ingredient]')) e.target.closest('.recipe-row').remove(); });
});
const ingredientForm = document.querySelector('[data-ingredient-form]');
if (ingredientForm) {
    const update = () => {
        const isNew = !ingredientForm.elements.ingredient_id.value;
        const isLoss = ingredientForm.elements.kind.value === 'merma';
        ingredientForm.querySelector('[data-new-ingredient]').hidden = !isNew;
        ingredientForm.elements.name.required = isNew;
        ingredientForm.elements.notes.required = isLoss;
        ingredientForm.querySelector('[data-cost-field]').hidden = isLoss;
    };
    ingredientForm.addEventListener('change', update); update();
}
