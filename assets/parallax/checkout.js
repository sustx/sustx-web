'use strict';
(() => {
  const {json, money, saveSession, readSession} = window.ParallaxPurchase;
  const form = document.getElementById('checkout-form');
  const button = document.getElementById('checkout-pay');
  const feedback = document.getElementById('checkout-feedback');
  const discountFeedback = document.getElementById('discount-feedback');
  const inputs = [...form.querySelectorAll('input')];
  let available = false;
  let busy = false;
  function nonce() { return Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join(''); }
  let checkoutKey = nonce();
  const fields = () => ({customer: inputs[0].value.trim(), email: inputs[1].value.trim(),
    discount_code: document.getElementById('checkout-discount').value.trim(), referral: document.getElementById('checkout-referral').value.trim()});
  const restored = readSession('parallax.checkout-details');
  if (restored) {
    const values = [restored.customer, restored.email, restored.discount_code, restored.referral];
    inputs.forEach((input, index) => { input.value = typeof values[index] === 'string' ? values[index] : ''; });
  }
  function showPrice(price) {
    document.getElementById('checkout-subtotal').textContent = money(price.subtotal_cents);
    document.getElementById('checkout-total').textContent = money(price.total_cents);
    document.getElementById('checkout-saving-row').hidden = !price.discount_cents;
    document.getElementById('checkout-saving').textContent = '−' + money(price.discount_cents);
  }
  async function applyDiscount() {
    discountFeedback.textContent = '';
    const result = await json({action: 'checkout_quote', discount_code: fields().discount_code});
    showPrice(result.price);
    discountFeedback.textContent = result.price.discount_cents ? `Discount applied. You save ${money(result.price.discount_cents)}.` : '';
    return result.price;
  }
  document.getElementById('apply-discount').addEventListener('click', async event => {
    event.currentTarget.disabled = true;
    try { await applyDiscount(); }
    catch (error) { discountFeedback.textContent = error.message; showPrice({subtotal_cents: 5000, total_cents: 5000, discount_cents: 0}); }
    finally { document.getElementById('apply-discount').disabled = false; }
  });
  inputs.forEach(input => input.addEventListener('input', () => {
    checkoutKey = nonce();
    saveSession('parallax.checkout-details', fields());
    if (input.id === 'checkout-discount') {
      discountFeedback.textContent = '';
      showPrice({subtotal_cents: 5000, total_cents: 5000, discount_cents: 0});
    }
  }));
  const params = new URLSearchParams(location.search);
  if (params.get('ref')) document.getElementById('checkout-referral').value = params.get('ref').slice(0, 120);
  if (params.get('cancelled')) feedback.textContent = 'Checkout was cancelled. You can try again whenever you’re ready.';
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!available || busy) return;
    busy = true; button.disabled = true; button.textContent = 'Opening PayPal…'; feedback.textContent = '';
    inputs.forEach(input => { input.disabled = true; });
    document.getElementById('apply-discount').disabled = true;
    try {
      await applyDiscount();
      const result = await json({action: 'checkout_create', checkout_key: checkoutKey, ...fields()});
      saveSession('parallax.purchase:' + result.purchase_id, result.token);
      saveSession('parallax.checkout-details', fields());
      location.assign(result.approval_url);
    } catch (error) {
      feedback.textContent = error.message;
      busy = false; button.disabled = false; button.textContent = 'Continue to PayPal ↗';
      inputs.forEach(input => { input.disabled = false; });
      document.getElementById('apply-discount').disabled = false;
    }
  });
  (async () => {
    try {
      const config = await json({action: 'checkout_config'});
      available = config.ready;
      showPrice(config.price);
      document.getElementById('checkout-sandbox').hidden = config.mode !== 'sandbox' || !available;
      button.disabled = !available;
      if (!available) feedback.textContent = 'Purchasing is currently unavailable. Please try again later.';
      else if (!params.get('cancelled')) feedback.textContent = '';
    } catch { feedback.textContent = 'Checkout couldn’t load. Please refresh the page.'; }
  })();
})();
