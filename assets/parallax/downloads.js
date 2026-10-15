'use strict';
(async () => {
  try {
    const response = await fetch('/parallax/release.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error();
    const release = await response.json();
    document.getElementById('release-version').textContent = `v${release.version}`;
    for (const [id, key] of [['mac', 'mac'], ['windows', 'windows']]) {
      const file = release.files[key];
      const link = document.getElementById(`${id}-download`);
      link.href = file.url;
      link.download = file.filename;
      link.removeAttribute('aria-disabled');
    }
  } catch {
    document.getElementById('release-version').textContent = 'Parallax';
    document.getElementById('download-error').textContent = 'Downloads couldn’t load. Please refresh the page.';
  }
})();
