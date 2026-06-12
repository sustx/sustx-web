const DEFAULT_ARTIST = {
  name: "Sustancia 'X'",
  avatar: 'assets/profile.avif',
};

const STREAM_PLATFORMS = [
  {
    key: 'spotify',
    label: 'Listen on Spotify',
    cls: 'btn-spotify',
    icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.494 17.308a.748.748 0 01-1.029.249c-2.818-1.723-6.365-2.112-10.541-1.157a.748.748 0 01-.332-1.46c4.571-1.044 8.492-.595 11.655 1.339a.748.748 0 01.247 1.029zm1.466-3.26a.936.936 0 01-1.287.308c-3.225-1.982-8.141-2.556-11.956-1.399a.936.936 0 11-.543-1.791c4.358-1.323 9.776-.682 13.478 1.595a.936.936 0 01.308 1.287zm.126-3.395C15.53 8.398 9.4 8.192 5.97 9.246a1.123 1.123 0 11-.652-2.149c3.944-1.197 10.501-.965 14.641 1.768a1.123 1.123 0 01-1.374 1.788z"/></svg>',
  },
  {
    key: 'apple',
    label: 'Listen on Apple Music',
    cls: 'btn-apple',
    icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>',
  },
  {
    key: 'youtube',
    label: 'Watch on YouTube',
    cls: 'btn-youtube',
    icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M23.495 6.205a3.007 3.007 0 00-2.088-2.088c-1.87-.501-9.396-.501-9.396-.501s-7.507-.01-9.396.501A3.007 3.007 0 00.527 6.205a31.247 31.247 0 00-.522 5.805 31.247 31.247 0 00.522 5.783 3.007 3.007 0 002.088 2.088c1.868.502 9.396.502 9.396.502s7.506 0 9.396-.502a3.007 3.007 0 002.088-2.088 31.247 31.247 0 00.5-5.783 31.247 31.247 0 00-.5-5.805zM9.609 15.601V8.408l6.264 3.602z"/></svg>',
  },
];

let cachedSiteData = null;
let cachedSiteDataPromise = null;

function escapeAttribute(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function normalizeHexColor(value) {
  const raw = String(value ?? '').trim();
  return /^#[0-9a-f]{6}$/i.test(raw) ? raw : '#7c3aed';
}

function buildArtSources(path) {
  if (!path) {
    return null;
  }

  const match = path.match(/^(.*)\.avif$/i);
  if (!match) {
    return {
      src: path,
      srcSet: path,
      preload: path,
    };
  }

  const [, base] = match;

  return {
    src: `${base}.avif`,
    srcSet: `${base}-320.avif 320w, ${base}.avif 640w`,
    preload: `${base}.avif`,
  };
}

function buildResponsivePictureHTML(artSources, alt, sizes, options = {}) {
  if (!artSources) {
    return `<div class="placeholder-art">🎵</div>`;
  }

  const {
    className = '',
    loading = 'lazy',
    decoding = 'async',
    fetchPriority = '',
    onerror = '',
    ariaHidden = false,
  } = options;

  const classAttr = className ? ` class="${escapeAttribute(className)}"` : '';
  const loadingAttr = loading ? ` loading="${escapeAttribute(loading)}"` : '';
  const decodingAttr = decoding ? ` decoding="${escapeAttribute(decoding)}"` : '';
  const fetchPriorityAttr = fetchPriority ? ` fetchpriority="${escapeAttribute(fetchPriority)}"` : '';
  const onerrorAttr = onerror ? ` onerror="${escapeAttribute(onerror)}"` : '';
  const ariaHiddenAttr = ariaHidden ? ' aria-hidden="true"' : '';

  return `<img src="${escapeAttribute(artSources.src)}" srcset="${escapeAttribute(artSources.srcSet)}" sizes="${escapeAttribute(sizes)}" alt="${escapeAttribute(alt)}"${classAttr}${loadingAttr}${decodingAttr}${fetchPriorityAttr}${ariaHiddenAttr}${onerrorAttr} />`;
}

function normalizeSong(song, index, artistName) {
  const title = String(song?.title ?? '').trim() || `Untitled Song ${index + 1}`;
  const subtitle = String(song?.subtitle ?? '').trim();
  const art = String(song?.art ?? '').trim();

  return {
    id: String(song?.id ?? '').trim() || `song-${index + 1}`,
    title,
    subtitle,
    art,
    color: normalizeHexColor(song?.color),
    links: {
      spotify: String(song?.links?.spotify ?? '').trim(),
      apple: String(song?.links?.apple ?? '').trim(),
      youtube: String(song?.links?.youtube ?? '').trim(),
    },
    artSources: buildArtSources(art),
    artistName,
  };
}

function normalizeSiteData(payload) {
  const artist = {
    name: String(payload?.artist?.name ?? '').trim() || DEFAULT_ARTIST.name,
    avatar: String(payload?.artist?.avatar ?? '').trim() || DEFAULT_ARTIST.avatar,
  };

  const songs = Array.isArray(payload?.songs)
    ? payload.songs.map((song, index) => normalizeSong(song, index, artist.name))
    : [];

  return { artist, songs };
}

async function fetchSiteData({ force = false } = {}) {
  if (!force && cachedSiteData) {
    return cachedSiteData;
  }

  if (!force && cachedSiteDataPromise) {
    return cachedSiteDataPromise;
  }

  cachedSiteDataPromise = fetch('/api/site-data', {
    cache: 'no-store',
    headers: {
      Accept: 'application/json',
    },
  })
    .then(async response => {
      if (!response.ok) {
        throw new Error(`Failed to fetch site data (${response.status}).`);
      }

      return response.json();
    })
    .then(siteData => {
      cachedSiteData = normalizeSiteData(siteData);
      return cachedSiteData;
    })
    .catch(error => {
      cachedSiteDataPromise = null;
      throw error;
    });

  return cachedSiteDataPromise;
}

window.siteDataUtils = {
  DEFAULT_ARTIST,
  STREAM_PLATFORMS,
  buildArtSources,
  buildResponsivePictureHTML,
  fetchSiteData,
  normalizeHexColor,
  normalizeSiteData,
};
