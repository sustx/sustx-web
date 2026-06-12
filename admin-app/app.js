const statusBanner = document.getElementById('status-banner');
const artistFields = document.getElementById('artist-fields');
const songsStack = document.getElementById('songs-stack');
const saveButton = document.getElementById('save-btn');
const reloadButton = document.getElementById('reload-btn');
const addSongButton = document.getElementById('add-song-btn');

let siteData = null;
let isDirty = false;
let publicSiteUrl = '';
const EMPTY_PREVIEW = "data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 640'%3E%3Crect width='640' height='640' fill='%23171717'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='72' fill='%23666'%3EPreview%3C/text%3E%3C/svg%3E";

function slugify(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[^\w\s-]/g, '')
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function createDefaultSong() {
  return {
    id: '',
    title: '',
    subtitle: '',
    art: '',
    color: '#7c3aed',
    links: {
      spotify: '',
      apple: '',
      youtube: '',
    },
  };
}

function setStatus(message, tone = '') {
  statusBanner.textContent = message;
  statusBanner.className = `status-banner${tone ? ` is-${tone}` : ''}`;
}

function markDirty() {
  isDirty = true;
  setStatus('You have unsaved changes.');
}

function resolveMediaUrl(value) {
  const url = String(value ?? '').trim();
  if (!url) {
    return EMPTY_PREVIEW;
  }

  if (/^(https?:)?\/\//i.test(url) || url.startsWith('data:')) {
    return url;
  }

  if (!publicSiteUrl) {
    return EMPTY_PREVIEW;
  }

  return `${publicSiteUrl}/${url.replace(/^\/+/, '')}`;
}

function createField(labelText, value, options = {}) {
  const field = document.createElement('div');
  field.className = 'field';

  const label = document.createElement('label');
  label.textContent = labelText;

  const input = document.createElement('input');
  input.type = options.type || 'text';
  input.placeholder = options.placeholder || '';
  input.value = value || '';

  field.append(label, input);

  if (options.helpText) {
    const help = document.createElement('small');
    help.textContent = options.helpText;
    field.appendChild(help);
  }

  return { field, input };
}

function createUploadControl(labelText, onPick) {
  const field = document.createElement('div');
  field.className = 'field';

  const label = document.createElement('label');
  label.textContent = labelText;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary-btn';
  button.textContent = 'Upload image';

  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';

  button.addEventListener('click', () => input.click());
  input.addEventListener('change', async event => {
    const [file] = event.target.files || [];
    if (!file) {
      return;
    }

    await onPick(file);
    input.value = '';
  });

  field.append(label, button, input);
  return field;
}

async function uploadImage(file, kind, slug) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('kind', kind);
  formData.append('slug', slug || `${kind}-${Date.now()}`);

  const response = await fetch('/api/upload', {
    method: 'POST',
    body: formData,
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || 'Upload failed.');
  }

  return payload.url;
}

function renderArtistSection() {
  artistFields.innerHTML = '';

  const nameField = createField('Artist name', siteData.artist.name, {
    placeholder: "Sustancia 'X'",
  });
  nameField.input.addEventListener('input', event => {
    siteData.artist.name = event.target.value;
    markDirty();
  });

  const avatarField = createField('Avatar URL', siteData.artist.avatar, {
    placeholder: 'https://…',
  });
  avatarField.input.addEventListener('input', event => {
    siteData.artist.avatar = event.target.value;
    previewImage.src = resolveMediaUrl(siteData.artist.avatar);
    markDirty();
  });

  const previewCard = document.createElement('div');
  previewCard.className = 'preview-card';

  const previewImage = document.createElement('img');
  previewImage.alt = 'Artist avatar preview';
  previewImage.src = resolveMediaUrl(siteData.artist.avatar);
  previewCard.appendChild(previewImage);

  const uploadField = createUploadControl('Upload avatar', async file => {
    try {
      setStatus('Uploading avatar…');
      const url = await uploadImage(file, 'avatar', slugify(siteData.artist.name) || 'artist-avatar');
      siteData.artist.avatar = url;
      renderArtistSection();
      markDirty();
      setStatus('Avatar uploaded. Save to publish.');
    } catch (error) {
      setStatus(error.message, 'error');
    }
  });

  artistFields.append(nameField.field, avatarField.field, uploadField, previewCard);
}

function renderSongs() {
  songsStack.innerHTML = '';

  if (!siteData.songs.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No songs yet. Add your first release.';
    songsStack.appendChild(empty);
    return;
  }

  siteData.songs.forEach((song, index) => {
    const editor = document.createElement('article');
    editor.className = 'song-editor';

    const header = document.createElement('div');
    header.className = 'song-header';

    const titleWrap = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = song.title || `Song ${index + 1}`;
    const order = document.createElement('p');
    order.className = 'song-order';
    order.textContent = index === 0 ? 'Top of public list' : `Position ${index + 1}`;
    titleWrap.append(title, order);

    const controls = document.createElement('div');
    controls.className = 'song-controls';

    const moveUp = document.createElement('button');
    moveUp.type = 'button';
    moveUp.className = 'ghost-btn';
    moveUp.textContent = 'Move up';
    moveUp.disabled = index === 0;
    moveUp.addEventListener('click', () => {
      [siteData.songs[index - 1], siteData.songs[index]] = [siteData.songs[index], siteData.songs[index - 1]];
      renderSongs();
      markDirty();
    });

    const moveDown = document.createElement('button');
    moveDown.type = 'button';
    moveDown.className = 'ghost-btn';
    moveDown.textContent = 'Move down';
    moveDown.disabled = index === siteData.songs.length - 1;
    moveDown.addEventListener('click', () => {
      [siteData.songs[index + 1], siteData.songs[index]] = [siteData.songs[index], siteData.songs[index + 1]];
      renderSongs();
      markDirty();
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'danger-btn';
    remove.textContent = 'Delete';
    remove.addEventListener('click', () => {
      siteData.songs.splice(index, 1);
      renderSongs();
      markDirty();
    });

    controls.append(moveUp, moveDown, remove);
    header.append(titleWrap, controls);

    const grid = document.createElement('div');
    grid.className = 'song-grid';

    const artPanel = document.createElement('div');
    artPanel.className = 'song-art-panel';

    const artPreview = document.createElement('div');
    artPreview.className = 'song-art-preview';
    const artImage = document.createElement('img');
    artImage.alt = `${song.title || 'Song'} artwork preview`;
    artImage.src = resolveMediaUrl(song.art);
    artPreview.appendChild(artImage);

    const artField = createField('Artwork URL', song.art, {
      placeholder: 'https://…',
    });
    artField.input.addEventListener('input', event => {
      song.art = event.target.value;
      artImage.src = resolveMediaUrl(song.art);
      markDirty();
    });

    const uploadArt = createUploadControl('Upload artwork', async file => {
      try {
        setStatus(`Uploading artwork for ${song.title || 'song'}…`);
        const slug = slugify(song.id || song.title || `song-${index + 1}`) || `song-${index + 1}`;
        const url = await uploadImage(file, 'song', slug);
        song.art = url;
        renderSongs();
        markDirty();
        setStatus('Artwork uploaded. Save to publish.');
      } catch (error) {
        setStatus(error.message, 'error');
      }
    });

    artPanel.append(artPreview, artField.field, uploadArt);

    const fields = document.createElement('div');
    fields.className = 'song-fields';

    const rowOne = document.createElement('div');
    rowOne.className = 'field-row';
    const rowTwo = document.createElement('div');
    rowTwo.className = 'field-row';
    const rowThree = document.createElement('div');
    rowThree.className = 'field-row three-up';

    const titleField = createField('Title', song.title, {
      placeholder: 'Song title',
    });
    titleField.input.addEventListener('input', event => {
      song.title = event.target.value;
      title.textContent = song.title || `Song ${index + 1}`;
      markDirty();
    });

    const subtitleField = createField('Subtitle', song.subtitle, {
      placeholder: 'Single · 2026',
    });
    subtitleField.input.addEventListener('input', event => {
      song.subtitle = event.target.value;
      markDirty();
    });

    const slugField = createField('Slug / URL id', song.id, {
      placeholder: 'auto-from-title',
      helpText: 'Used in song.html?id=…',
    });
    slugField.input.addEventListener('input', event => {
      song.id = slugify(event.target.value);
      event.target.value = song.id;
      markDirty();
    });

    const colorField = createField('Accent color', song.color, {
      placeholder: '#7c3aed',
    });
    colorField.input.addEventListener('input', event => {
      song.color = event.target.value.trim() || '#7c3aed';
      markDirty();
    });

    const spotifyField = createField('Spotify link', song.links.spotify, {
      placeholder: 'https://open.spotify.com/…',
    });
    spotifyField.input.addEventListener('input', event => {
      song.links.spotify = event.target.value;
      markDirty();
    });

    const appleField = createField('Apple Music link', song.links.apple, {
      placeholder: 'https://music.apple.com/…',
    });
    appleField.input.addEventListener('input', event => {
      song.links.apple = event.target.value;
      markDirty();
    });

    const youtubeField = createField('YouTube link', song.links.youtube, {
      placeholder: 'https://www.youtube.com/watch?v=…',
    });
    youtubeField.input.addEventListener('input', event => {
      song.links.youtube = event.target.value;
      markDirty();
    });

    rowOne.append(titleField.field, subtitleField.field);
    rowTwo.append(slugField.field, colorField.field);
    rowThree.append(spotifyField.field, appleField.field, youtubeField.field);
    fields.append(rowOne, rowTwo, rowThree);

    grid.append(artPanel, fields);
    editor.append(header, grid);
    songsStack.appendChild(editor);
  });
}

function render() {
  renderArtistSection();
  renderSongs();
}

async function loadSiteData() {
  setStatus('Loading site data…');

  const response = await fetch('/api/site-data', {
    headers: {
      Accept: 'application/json',
    },
  });
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || 'Failed to load site data.');
  }

  siteData = payload.data;
  publicSiteUrl = payload.publicSiteUrl || '';
  isDirty = false;
  render();
  setStatus('Loaded current site data.');
}

async function saveSiteData() {
  if (!siteData) {
    return;
  }

  saveButton.disabled = true;
  setStatus('Saving changes…');

  try {
    const response = await fetch('/api/site-data', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(siteData),
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || 'Failed to save site data.');
    }

    siteData = payload.data;
    publicSiteUrl = payload.publicSiteUrl || '';
    isDirty = false;
    render();
    setStatus('Saved. Public site updates will follow the short cache window.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    saveButton.disabled = false;
  }
}

reloadButton.addEventListener('click', async () => {
  try {
    await loadSiteData();
  } catch (error) {
    setStatus(error.message, 'error');
  }
});

saveButton.addEventListener('click', saveSiteData);

addSongButton.addEventListener('click', () => {
  siteData.songs.unshift(createDefaultSong());
  renderSongs();
  markDirty();
});

window.addEventListener('beforeunload', event => {
  if (!isDirty) {
    return;
  }

  event.preventDefault();
  event.returnValue = '';
});

loadSiteData().catch(error => {
  setStatus(error.message, 'error');
});
