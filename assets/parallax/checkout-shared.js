'use strict';
window.ParallaxPurchase = (() => {
  async function request(data) {
    const response = await fetch('/api/parallax', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', referrerPolicy: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || 'Unable to continue right now. Please try again.');
    }
    return response;
  }
  const json = async data => (await request(data)).json();
  const money = cents => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(cents / 100);
  function saveSession(key, value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch {} }
  function readSession(key) { try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { return null; } }
  function activationLink(token) {
    const link = new URL('/parallax/activate/', location.origin);
    link.hash = new URLSearchParams({purchase: token}).toString();
    return link.href;
  }
  async function file(response) {
    const filename = response.headers.get('Content-Disposition')?.match(/filename="([\w.-]+)"/)?.[1];
    if (!filename) throw new Error('The file download was incomplete. Please try again.');
    return new File([await response.blob()], filename, {type: response.headers.get('Content-Type') || 'application/octet-stream'});
  }
  function download(file) {
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url; link.download = file.name;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  return {request, json, money, saveSession, readSession, activationLink, file, download};
})();
