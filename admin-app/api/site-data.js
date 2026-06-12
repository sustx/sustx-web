import { BlobNotFoundError, head, put } from '@vercel/blob';
import { readFile } from 'node:fs/promises';

const SITE_DATA_PATH = 'site-data.json';
const FALLBACK_FILE_URL = new URL('../site-data.default.json', import.meta.url);

function hasBlobConfig() {
  return Boolean(
    process.env.BLOB_READ_WRITE_TOKEN
      || (process.env.BLOB_STORE_ID && process.env.VERCEL_OIDC_TOKEN),
  );
}

function slugify(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[^\w\s-]/g, '')
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function normalizeHexColor(value) {
  const raw = String(value ?? '').trim();
  return /^#[0-9a-f]{6}$/i.test(raw) ? raw : '#7c3aed';
}

function normalizeUrl(value) {
  return String(value ?? '').trim();
}

function normalizeSong(song, index) {
  const title = String(song?.title ?? '').trim() || `Untitled Song ${index + 1}`;
  const id = slugify(song?.id || title || `song-${index + 1}`);

  if (!id) {
    throw new Error(`Song ${index + 1} is missing a valid id.`);
  }

  return {
    id,
    title,
    subtitle: String(song?.subtitle ?? '').trim(),
    art: normalizeUrl(song?.art),
    color: normalizeHexColor(song?.color),
    links: {
      spotify: normalizeUrl(song?.links?.spotify),
      apple: normalizeUrl(song?.links?.apple),
      youtube: normalizeUrl(song?.links?.youtube),
    },
  };
}

function normalizeSiteData(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Invalid site data payload.');
  }

  const artist = {
    name: String(payload.artist?.name ?? '').trim() || "Sustancia 'X'",
    avatar: normalizeUrl(payload.artist?.avatar) || 'assets/profile.avif',
  };

  if (!Array.isArray(payload.songs)) {
    throw new Error('Songs payload must be an array.');
  }

  const songs = payload.songs.map(normalizeSong);
  const ids = new Set();

  songs.forEach(song => {
    if (ids.has(song.id)) {
      throw new Error(`Duplicate song id: ${song.id}`);
    }
    ids.add(song.id);
  });

  return { artist, songs };
}

async function readFallbackSiteData() {
  const raw = await readFile(FALLBACK_FILE_URL, 'utf8');
  return JSON.parse(raw);
}

async function readBlobSiteData() {
  if (!hasBlobConfig()) {
    return null;
  }

  try {
    const blob = await head(SITE_DATA_PATH);
    const response = await fetch(blob.url, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`Failed to fetch blob site data (${response.status}).`);
    }

    return response.json();
  } catch (error) {
    if (error instanceof BlobNotFoundError) {
      return null;
    }

    throw error;
  }
}

async function loadSiteData() {
  const blobData = await readBlobSiteData();
  if (blobData) {
    return normalizeSiteData(blobData);
  }

  return normalizeSiteData(await readFallbackSiteData());
}

function getPublicSiteUrl() {
  return String(process.env.PUBLIC_SITE_URL ?? '').trim().replace(/\/+$/, '');
}

export async function GET() {
  try {
    return Response.json({
      data: await loadSiteData(),
      publicSiteUrl: getPublicSiteUrl(),
    }, {
      headers: {
        'Cache-Control': 'private, no-store',
      },
    });
  } catch (error) {
    console.error('Failed to load admin site data.', error);
    return Response.json(
      { error: 'Failed to load site data.' },
      {
        status: 500,
        headers: {
          'Cache-Control': 'no-store',
        },
      },
    );
  }
}

export async function PUT(request) {
  try {
    if (!hasBlobConfig()) {
      return Response.json(
        {
          error: 'Blob storage is not configured. Connect a public Blob store to this Vercel project first.',
        },
        { status: 500, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    const payload = await request.json();
    const siteData = normalizeSiteData(payload);

    await put(SITE_DATA_PATH, JSON.stringify(siteData, null, 2), {
      access: 'public',
      allowOverwrite: true,
      cacheControlMaxAge: 60,
      contentType: 'application/json; charset=utf-8',
    });

    return Response.json(
      {
        ok: true,
        data: siteData,
        publicSiteUrl: getPublicSiteUrl(),
      },
      {
        headers: {
          'Cache-Control': 'no-store',
        },
      },
    );
  } catch (error) {
    console.error('Failed to save site data.', error);
    return Response.json(
      { error: error instanceof Error ? error.message : 'Failed to save site data.' },
      {
        status: 400,
        headers: {
          'Cache-Control': 'no-store',
        },
      },
    );
  }
}
