'use strict';
const api = '/api/parallax';
const loginPanel = document.getElementById('login-panel');
const issuerPanel = document.getElementById('issuer-panel');
const feedback = document.getElementById('admin-feedback');
const ready = document.getElementById('license-ready');
let csrf = null;
let licenseFile = null;

function showSession(session) {
  csrf = session.csrf || null;
  loginPanel.hidden = session.authenticated;
  issuerPanel.hidden = !session.authenticated;
  document.getElementById('loading').hidden = true;
  if (!session.authenticated) {
    licenseFile = null;
    ready.hidden = true;
    document.getElementById('issue-form').reset();
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
    ready.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
  });
});

document.getElementById('save-license').addEventListener('click', () => {
  if (!licenseFile) return;
  const url = URL.createObjectURL(licenseFile);
  const link = document.createElement('a');
  link.href = url; link.download = licenseFile.name;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
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
