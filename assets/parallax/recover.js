'use strict';
(() => {
  const form = document.getElementById('purchase-recovery-form');
  const feedback = document.getElementById('purchase-recovery-feedback');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true; feedback.textContent = ''; button.textContent = 'One moment…';
    try {
      const result = await window.ParallaxPurchase.json({action: 'purchase_recover', email: document.getElementById('purchase-recovery-email').value.trim()});
      feedback.textContent = result.message;
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; button.textContent = 'Email my activation link ↗'; }
  });
})();
