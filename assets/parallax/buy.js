'use strict';
(() => {
  const button = document.querySelector('.buy-button');
  if (!button) return;
  fetch('/api/parallax', {method: 'POST', credentials: 'omit', cache: 'no-store',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'checkout_config'})})
    .then(response => response.ok ? response.json() : Promise.reject())
    .then(config => {
      if (!config.ready) return;
      button.disabled = false;
      button.removeAttribute('title');
      button.setAttribute('aria-label', 'Buy Parallax for $50 USD');
      button.addEventListener('click', () => {
        const url = new URL('/parallax/checkout/', location.origin);
        const referral = new URLSearchParams(location.search).get('ref');
        if (referral) url.searchParams.set('ref', referral.slice(0, 120));
        location.assign(url.href);
      });
    }).catch(() => {});
})();
