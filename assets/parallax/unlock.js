'use strict';
const form = document.getElementById('unlock-form');
const invitation = document.getElementById('invitation');
const status = document.getElementById('invitation-status');
const feedback = document.getElementById('unlock-feedback');
const ready = document.getElementById('unlock-ready');
let license = null;
let checkGeneration = 0;

function invitationCode(value) {
  value = value.trim();
  if (value.startsWith('PLXI-')) return value;
  try { return new URLSearchParams(new URL(value).hash.slice(1)).get('invite') || ''; }
  catch { return ''; }
}

async function request(data) {
  const response = await fetch('/api/parallax', {
    method: 'POST', credentials: 'omit', cache: 'no-store', referrerPolicy: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(result.error || 'Unable to unlock right now. Please try again.');
  }
  return response;
}

function resetDownload() { license = null; ready.hidden = true; feedback.textContent = ''; }

async function checkInvitation() {
  const generation = ++checkGeneration;
  const token = invitationCode(invitation.value);
  status.textContent = '';
  if (!token) return;
  try {
    const result = await (await request({ action: 'invite_status', token })).json();
    if (generation !== checkGeneration) return;
    status.textContent = result.status === 'redeemed'
      ? 'Already unlocked. Use the same email and plugin code to download your license again.'
      : 'Your invitation is ready.';
  } catch (error) { if (generation === checkGeneration) status.textContent = error.message; }
}

invitation.addEventListener('input', () => { ++checkGeneration; status.textContent = ''; resetDownload(); });
invitation.addEventListener('change', checkInvitation);
for (const id of ['customer', 'email', 'request']) document.getElementById(id).addEventListener('input', resetDownload);
form.addEventListener('submit', async event => {
  event.preventDefault(); resetDownload();
  const button = form.querySelector('button[type=submit]');
  const token = invitationCode(invitation.value);
  if (!token) { feedback.textContent = 'Paste your invitation code or the complete link you received.'; return; }
  button.disabled = true; button.textContent = 'One moment…';
  const inputs = [...form.querySelectorAll('input, textarea')];
  inputs.forEach(input => { input.disabled = true; });
  try {
    const response = await request({ action: 'redeem', token,
      customer: document.getElementById('customer').value.trim(),
      email: document.getElementById('email').value.trim(),
      request: document.getElementById('request').value.trim(),
    });
    const filename = response.headers.get('Content-Disposition')?.match(/filename="([\w.-]+)"/)?.[1];
    if (!filename) throw new Error('Please try again to download your original license.');
    license = new File([await response.blob()], filename, { type: 'application/octet-stream' });
    ready.hidden = false;
    status.textContent = 'This invitation has unlocked your computer.';
    ready.scrollIntoView({ block: 'nearest' });
  } catch (error) { feedback.textContent = error.message; }
  finally { button.disabled = false; button.textContent = 'Get my license ↓'; inputs.forEach(input => { input.disabled = false; }); }
});

document.getElementById('download-license').addEventListener('click', () => {
  if (!license) return;
  const url = URL.createObjectURL(license);
  const link = document.createElement('a'); link.href = url; link.download = license.name;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
});

function loadInvitation() {
  const token = new URLSearchParams(location.hash.slice(1)).get('invite');
  if (token) { invitation.value = token; resetDownload(); checkInvitation(); }
}
window.addEventListener('hashchange', loadInvitation);
loadInvitation();
