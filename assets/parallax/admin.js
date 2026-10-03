'use strict';
const api = '/api/parallax';
const loginPanel = document.getElementById('login-panel');
const issuerPanel = document.getElementById('issuer-panel');
const feedback = document.getElementById('admin-feedback');
const ready = document.getElementById('license-ready');
let csrf = null;
let licenseFile = null;
let records = [];
let historyLoading = false;
let historyRefreshPending = false;
let invitesLoading = false;
let invitesRefreshPending = false;
const historyFeedback = document.getElementById('history-feedback');

function showSession(session) {
  csrf = session.csrf || null;
  loginPanel.hidden = session.authenticated;
  issuerPanel.hidden = !session.authenticated;
  document.getElementById('loading').hidden = true;
  if (!session.authenticated) {
    licenseFile = null;
    ready.hidden = true;
    document.getElementById('issue-form').reset();
    records = [];
    document.getElementById('history-list').replaceChildren();
    document.getElementById('history-search').value = '';
    document.getElementById('import-form').reset();
    document.getElementById('import-feedback').textContent = '';
    historyFeedback.textContent = '';
    document.getElementById('invite-form').reset();
    document.getElementById('invite-ready').hidden = true;
    document.getElementById('invite-link').value = '';
    document.getElementById('invite-list').replaceChildren();
    document.getElementById('invite-feedback').textContent = '';
  } else {
    refreshHistory();
    refreshInvites();
  }
}

async function request(data) {
  const response = await fetch(api, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf || '' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    if (response.status === 401 && data.action !== 'login') showSession({ authenticated: false });
    throw new Error(result.error || 'Something went wrong. Please try again.');
  }
  return response;
}

async function busy(form, callback) {
  const button = form.querySelector('button[type=submit]');
  const original = button.textContent;
  button.disabled = true;
  button.textContent = 'One moment…';
  feedback.textContent = '';
  try { await callback(); }
  catch (error) { feedback.textContent = error.message; }
  finally { button.disabled = false; button.textContent = original; }
}

document.getElementById('login-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.currentTarget, async () => {
    const input = document.getElementById('password');
    const password = input.value;
    input.value = '';
    const response = await request({ action: 'login', password });
    showSession(await response.json());
    document.getElementById('customer').focus();
  });
});

document.getElementById('issue-form').addEventListener('submit', event => {
  event.preventDefault();
  ready.hidden = true;
  licenseFile = null;
  busy(event.currentTarget, async () => {
    const customer = document.getElementById('customer').value.trim();
    const code = document.getElementById('request').value.trim();
    const response = await request({ action: 'issue', customer, request: code });
    const blob = await response.blob();
    const filename = response.headers.get('Content-Disposition')?.match(/filename="([\w.-]+)"/)?.[1];
    if (!filename) throw new Error('The license download was incomplete. Please try again.');
    licenseFile = new File([blob], filename, { type: 'application/octet-stream' });
    document.getElementById('license-customer').textContent = `License for ${customer} · ${code.startsWith('PLX1-MAC-') ? 'macOS' : 'Windows'}`;
    const share = document.getElementById('share-license');
    share.hidden = !(navigator.canShare && navigator.canShare({ files: [licenseFile] }));
    ready.hidden = false;
    await refreshHistory();
    ready.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
  });
});

document.getElementById('save-license').addEventListener('click', () => {
  if (!licenseFile) return;
  saveFile(licenseFile);
});

function saveFile(file) {
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url; link.download = file.name;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

async function responseFile(response, fallback) {
  const name = response.headers.get('Content-Disposition')?.match(/filename="([\w.-]+)"/)?.[1] || fallback;
  return new File([await response.blob()], name, { type: response.headers.get('Content-Type') || 'application/octet-stream' });
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function dateLabel(date) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date));
}

function renderHistory() {
  const query = document.getElementById('history-search').value.trim().toLowerCase();
  const matches = records.filter(record => [record.customer, record.email || '', record.machine, record.license_id, record.platform].some(value => value.toLowerCase().includes(query)));
  const list = document.getElementById('history-list');
  list.replaceChildren();
  document.getElementById('record-count').textContent = `${records.length} ${records.length === 1 ? 'license' : 'licenses'}`;
  if (!records.length) historyFeedback.textContent = 'No licenses recorded yet. New licenses are saved here automatically.';
  else if (!matches.length) historyFeedback.textContent = 'No records match that search.';
  else historyFeedback.textContent = query ? `${matches.length} matching ${matches.length === 1 ? 'record' : 'records'}.` : '';
  for (const record of matches) {
    const card = element('article', undefined, 'history-record');
    const header = element('div', undefined, 'section-top');
    header.append(element('h3', record.customer), element('span', record.platform, 'version'));
    card.append(header, element('p', `Issued ${dateLabel(record.issued_at)}`, 'field-help'));
    const details = element('details');
    details.append(element('summary', 'License details'));
    const fields = element('dl');
    for (const [label, value] of [['Email', record.email || '—'], ['License ID', record.license_id], ['Computer code', record.machine], ['Added to records', dateLabel(record.recorded_at)], ['Source', record.source === 'imported' ? 'Imported license' : record.source === 'invitation' ? 'Invitation unlock' : 'License desk']]) {
      fields.append(element('dt', label), element('dd', value));
    }
    details.append(fields);
    const download = element('button', 'Download license ↓', 'secondary-button');
    download.type = 'button';
    download.addEventListener('click', async () => {
      download.disabled = true;
      try {
        const response = await request({ action: 'download', license_id: record.license_id });
        saveFile(await responseFile(response, `Parallax-${record.license_id}.parallax-license`));
      } catch (error) { historyFeedback.textContent = error.message; }
      finally { download.disabled = false; }
    });
    card.append(details, download);
    list.append(card);
  }
}

async function refreshHistory() {
  if (!csrf) return;
  if (historyLoading) { historyRefreshPending = true; return; }
  historyLoading = true;
  const tokenAtStart = csrf;
  historyFeedback.textContent = 'Loading customer records…';
  try {
    const response = await request({ action: 'history' });
    const result = await response.json();
    if (csrf !== tokenAtStart) return;
    records = result.records;
    renderHistory();
  } catch (error) {
    if (csrf === tokenAtStart) {
      historyFeedback.textContent = error.message;
      document.getElementById('record-count').textContent = 'Unavailable';
    }
  } finally {
    historyLoading = false;
    if (historyRefreshPending) { historyRefreshPending = false; refreshHistory(); }
  }
}

document.getElementById('history-search').addEventListener('input', renderHistory);
document.getElementById('refresh-history').addEventListener('click', refreshHistory);
document.getElementById('export-history').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  try { saveFile(await responseFile(await request({ action: 'export' }), 'Parallax-license-history.csv')); }
  catch (error) { historyFeedback.textContent = error.message; }
  finally { button.disabled = false; }
});

document.getElementById('import-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  const importFeedback = document.getElementById('import-feedback');
  importFeedback.textContent = '';
  busy(form, async () => {
    const file = document.getElementById('import-file').files[0];
    if (!file || file.size > 16384) throw new Error('Choose a Parallax license file smaller than 16 KB.');
    const result = await (await request({ action: 'import', document: await file.text() })).json();
    importFeedback.textContent = `Saved the license for ${result.record.customer}.`;
    form.reset();
    await refreshHistory();
  });
});

document.getElementById('share-license').addEventListener('click', async () => {
  if (!licenseFile) return;
  try { await navigator.share({ files: [licenseFile], title: 'Parallax license' }); }
  catch (error) { if (error.name !== 'AbortError') feedback.textContent = 'Sharing failed. Use Download license to save the file.'; }
});

document.getElementById('logout').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  try { await request({ action: 'logout' }); showSession({ authenticated: false }); feedback.textContent = ''; }
  catch (error) { feedback.textContent = error.message; }
  finally { button.disabled = false; }
});

(async () => {
  try {
    const response = await fetch(api, { credentials: 'same-origin', cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Owner access is unavailable.');
    showSession(result);
  } catch (error) {
    document.getElementById('loading').hidden = true;
    feedback.textContent = error.message;
  }
})();

async function refreshInvites() {
  if (!csrf) return;
  if (invitesLoading) { invitesRefreshPending = true; return; }
  invitesLoading = true;
  const tokenAtStart = csrf;
  const message = document.getElementById('invite-feedback');
  message.textContent = 'Loading invitations…';
  try {
    const result = await (await request({ action: 'invites' })).json();
    if (csrf !== tokenAtStart) return;
    const list = document.getElementById('invite-list');
    list.replaceChildren();
    document.getElementById('invite-count').textContent = `${result.invitations.length} invitations`;
    message.textContent = result.invitations.length ? '' : 'No invitations yet.';
    for (const invite of result.invitations) {
      const card = element('article', undefined, 'history-record');
      const header = element('div', undefined, 'section-top');
      header.append(element('h3', invite.email || 'Any recipient'), element('span', invite.status, 'version invite-state'));
      card.append(header, element('p', `Created ${dateLabel(invite.created_at)} · Expires ${dateLabel(invite.expires_at)}`, 'field-help'));
      if (invite.customer) card.append(element('p', `Unlocked by ${invite.customer}`, 'field-help'));
      if (invite.status === 'ready' || invite.status === 'redeemed') {
        const revoke = element('button', 'Revoke invitation', 'secondary-button invite-revoke');
        revoke.type = 'button';
        revoke.addEventListener('click', async () => {
          revoke.disabled = true;
          try {
            await request({ action: 'invite_revoke', invite_id: invite.invite_id });
            await refreshInvites();
          } catch (error) { message.textContent = error.message; }
          finally { revoke.disabled = false; }
        });
        card.append(revoke);
      }
      list.append(card);
    }
  } catch (error) {
    if (csrf === tokenAtStart) { message.textContent = error.message; document.getElementById('invite-count').textContent = 'Unavailable'; }
  } finally {
    invitesLoading = false;
    if (invitesRefreshPending) { invitesRefreshPending = false; refreshInvites(); }
  }
}

document.getElementById('refresh-invites').addEventListener('click', refreshInvites);
document.getElementById('invite-form').addEventListener('submit', event => {
  event.preventDefault();
  document.getElementById('invite-ready').hidden = true;
  document.getElementById('invite-link').value = '';
  busy(event.currentTarget, async () => {
    const tokenAtStart = csrf;
    const result = await (await request({ action: 'invite_create', email: document.getElementById('invite-email').value.trim(), days: Number(document.getElementById('invite-days').value) })).json();
    if (csrf !== tokenAtStart) return;
    const link = new URL('/parallax/unlock/', location.origin);
    link.hash = new URLSearchParams({ invite: result.token }).toString();
    document.getElementById('invite-link').value = link.href;
    document.getElementById('invite-ready').hidden = false;
    document.getElementById('invite-form').reset();
    await refreshInvites();
  });
});
document.getElementById('copy-invite').addEventListener('click', async () => {
  const input = document.getElementById('invite-link');
  if (!input.value) return;
  try { await navigator.clipboard.writeText(input.value); document.getElementById('invite-feedback').textContent = 'Invitation link copied.'; }
  catch { input.focus(); input.select(); document.getElementById('invite-feedback').textContent = 'Link selected. Copy it to share.'; }
});
