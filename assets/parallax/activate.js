'use strict';
(() => {
  const {json, request, money, readSession, saveSession, activationLink, file, download} = window.ParallaxPurchase;
  const loading = document.getElementById('activation-loading');
  const feedback = document.getElementById('activation-feedback');
  const form = document.getElementById('activation-form');
  const panel = document.getElementById('activation-panel');
  let token = new URLSearchParams(location.hash.slice(1)).get('purchase');
  let changing = false;
  let customerEmail = '';
  function entry(tag, value, className) {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    if (className) element.className = className;
    return element;
  }
  function show(result) {
    if (!result.paid) throw new Error('Payment has not been confirmed yet. Please finish PayPal checkout or use the activation link in your email.');
    document.getElementById('activation-sandbox').hidden = result.mode !== 'sandbox';
    document.getElementById('activation-name').textContent = result.customer;
    document.getElementById('activation-email').textContent = result.email;
    customerEmail = result.email;
    document.getElementById('activation-paid').textContent = money(result.price.total_cents) + ' USD';
    document.getElementById('activation-seats').textContent = `${result.activations.length} of ${result.seats} activated · ${result.remaining} available`;
    form.hidden = result.remaining === 0;
    const list = document.getElementById('activation-license-list');
    list.replaceChildren();
    document.getElementById('activation-licenses').hidden = result.activations.length === 0;
    result.activations.forEach((activation, index) => {
      const card = entry('article', undefined, 'activation-license');
      card.append(entry('h3', `Computer ${index + 1} · ${activation.platform}`), entry('p', activation.machine));
      const button = entry('button', 'Download license ↓', 'secondary-button');
      button.type = 'button';
      button.addEventListener('click', async () => {
        button.disabled = true; feedback.textContent = '';
        try { download(await file(await request({action: 'purchase_download', token, license_id: activation.license_id}))); }
        catch (error) { feedback.textContent = error.message; }
        finally { button.disabled = false; }
      });
      card.append(button); list.append(card);
    });
    panel.hidden = false;
  }
  document.getElementById('activation-receipt').addEventListener('click', async event => {
    const button = event.currentTarget; button.disabled = true; feedback.textContent = '';
    try { download(await file(await request({action: 'purchase_receipt', token}))); }
    catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (changing) return;
    changing = true; feedback.textContent = '';
    const button = form.querySelector('button');
    const input = document.getElementById('activation-request');
    button.disabled = true; input.disabled = true; button.textContent = 'Activating…';
    try {
      const license = await file(await request({action: 'purchase_redeem', token, request: input.value.trim()}));
      show(await json({action: 'purchase_status', token}));
      input.value = '';
      feedback.textContent = 'Your license is ready. Import the downloaded file into Parallax.';
      download(license);
    } catch (error) { feedback.textContent = error.message; }
    finally { changing = false; button.disabled = false; input.disabled = false; button.textContent = 'Activate this computer ↓'; }
  });
  document.getElementById('activation-copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(activationLink(token)); feedback.textContent = 'Your private activation link is copied.'; }
    catch { feedback.textContent = 'Copy the address from your browser to save this activation link.'; }
  });
  document.getElementById('activation-resend').addEventListener('click', async event => {
    const button = event.currentTarget; button.disabled = true;
    try { feedback.textContent = (await json({action: 'purchase_recover', email: customerEmail})).message; }
    catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  (async () => {
    try {
      const purchaseId = new URLSearchParams(location.search).get('checkout');
      if (!token && purchaseId) {
        token = readSession('parallax.purchase:' + purchaseId);
        if (!token) token = (await json({action: 'checkout_resume', purchase_id: purchaseId})).token;
      }
      if (!token) throw new Error('Open the private activation link from your email, or request it again below.');
      let result = await json({action: 'purchase_status', token});
      if (!result.paid) {
        loading.textContent = 'Confirming your PayPal payment…';
        result = await json({action: 'checkout_capture', token});
      }
      saveSession('parallax.purchase:' + result.purchase_id, token);
      history.replaceState(null, '', activationLink(token));
      show(result);
      try {
        const response = await fetch('/parallax/release.json', {cache: 'no-cache'});
        if (!response.ok) throw new Error();
        const release = await response.json();
        for (const platform of ['mac', 'windows']) {
          const link = document.getElementById('activation-' + platform);
          link.href = release.files[platform].url; link.download = release.files[platform].filename;
          link.removeAttribute('aria-disabled');
        }
      } catch { feedback.textContent = 'Installer links couldn’t load. You can also download Parallax from the product page.'; }
    } catch (error) {
      feedback.textContent = error.message;
      document.getElementById('activation-recovery').hidden = false;
    } finally { loading.hidden = true; }
  })();
})();
