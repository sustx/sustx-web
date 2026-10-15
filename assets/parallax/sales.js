'use strict';
(() => {
  let csrf = null;
  let rows = [];
  let generation = 0;
  const feedback = document.getElementById('sales-feedback');
  const list = document.getElementById('sales-list');
  const money = cents => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(cents / 100);
  const date = value => new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value));
  function node(tag, value, className) {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    if (className) element.className = className;
    return element;
  }
  async function api(data) {
    const response = await fetch('/api/parallax', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf || ''}, body: JSON.stringify(data)});
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'Sales could not load.');
    return response;
  }
  function render() {
    const query = document.getElementById('sales-search').value.trim().toLowerCase();
    const matches = rows.filter(row => [row.customer, row.email, row.referral, row.purchase_id, row.order_id, row.capture_id, row.price.discount_code].some(value => String(value || '').toLowerCase().includes(query)));
    list.replaceChildren();
    document.getElementById('sale-count').textContent = `${rows.length} purchases`;
    const live = rows.filter(row => row.mode === 'live');
    document.getElementById('sales-summary').textContent = `${live.length} live sales · ${money(live.reduce((sum, row) => sum + row.amount_cents, 0))} gross`;
    feedback.textContent = !rows.length ? 'No paid purchases yet.' : !matches.length ? 'No purchases match that search.' : '';
    for (const row of matches) {
      const card = node('article', undefined, 'history-record');
      const header = node('div', undefined, 'section-top');
      header.append(node('h3', row.customer), node('span', `${money(row.amount_cents)}${row.mode === 'sandbox' ? ' · Sandbox' : ''}`, 'version'));
      card.append(header, node('p', `${row.email} · Paid ${date(row.paid_at)}`, 'field-help'),
        node('p', `${row.activated} of ${row.seats} computers activated · Referral: ${row.referral || 'Direct'}`, 'field-help'));
      const details = node('details'); details.append(node('summary', 'Purchase details'));
      const fields = node('dl');
      for (const [label, value] of [['Purchase ID', row.purchase_id], ['Customer type', 'Paying customer'],
        ['List price', money(row.price.subtotal_cents)], ['Discount', `${money(row.price.discount_cents)} · ${row.price.discount_code || 'No code'}`],
        ['Paid', `${money(row.amount_cents)} ${row.currency}`], ['Referral (customer provided)', row.referral || 'Direct'],
        ['PayPal order', row.order_id], ['PayPal capture', row.capture_id], ['PayPal payer ID', row.payer_id || '—'],
        ['PayPal payer email', row.payer_email || '—'], ['Payer country', row.payer_country || '—'],
        ['PayPal fee', row.paypal_fee_cents === null ? 'Not supplied' : money(row.paypal_fee_cents)],
        ['Net received', row.net_cents === null ? 'Not supplied' : money(row.net_cents)],
        ['License IDs', row.license_ids.join(', ') || 'Not activated yet']]) {
        fields.append(node('dt', label), node('dd', value));
      }
      details.append(fields); card.append(details);
      for (const [label, action] of [['Copy activation link', 'sale_link'], ['Resend activation email', 'sale_resend']]) {
        const button = node('button', label, 'secondary-button'); button.type = 'button';
        button.addEventListener('click', async () => {
          button.disabled = true; feedback.textContent = '';
          try {
            const result = await (await api({action, purchase_id: row.purchase_id})).json();
            if (action === 'sale_link') {
              try { await navigator.clipboard.writeText(result.url); feedback.textContent = 'Private activation link copied.'; }
              catch {
                const input = node('input', undefined, 'history-search'); input.type = 'text'; input.readOnly = true; input.value = result.url;
                input.setAttribute('aria-label', 'Private activation link'); card.append(input); input.focus(); input.select();
                feedback.textContent = 'Link selected. Copy it to share privately.';
              }
            } else feedback.textContent = result.message;
          } catch (error) { feedback.textContent = error.message; }
          finally { button.disabled = false; }
        });
        card.append(button);
      }
      list.append(card);
    }
  }
  async function refresh() {
    if (!csrf) return;
    const ticket = ++generation;
    feedback.textContent = 'Loading purchases…';
    try {
      const result = await (await api({action: 'sales'})).json();
      if (ticket !== generation || !csrf) return;
      rows = result.sales; render();
    } catch (error) { if (ticket === generation && csrf) feedback.textContent = error.message; }
  }
  function showSession(session) {
    csrf = session.csrf || null;
    generation++;
    if (session.authenticated) refresh();
    else {
      rows = []; list.replaceChildren(); feedback.textContent = '';
      document.getElementById('sales-summary').textContent = '';
      document.getElementById('sales-search').value = '';
    }
  }
  window.addEventListener('parallax-session', event => showSession(event.detail));
  if (window.parallaxOwnerSession) showSession(window.parallaxOwnerSession);
  document.getElementById('sales-search').addEventListener('input', render);
  document.getElementById('refresh-sales').addEventListener('click', refresh);
  document.getElementById('export-sales').addEventListener('click', async event => {
    const button = event.currentTarget; button.disabled = true;
    try {
      const response = await api({action: 'sales_export'});
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = 'Parallax-sales.csv';
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
})();
