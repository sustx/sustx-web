import { BlobNotFoundError, head } from '@vercel/blob';
import { readFile } from 'node:fs/promises';

const SITE_DATA_PATH = 'site-data.json';
const FALLBACK_FILE_URL = new URL('../site-data.json', import.meta.url);

function hasBlobConfig() {
  return Boolean(
    process.env.BLOB_READ_WRITE_TOKEN
      || (process.env.BLOB_STORE_ID && process.env.VERCEL_OIDC_TOKEN),
  );
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
    return blobData;
  }

  return readFallbackSiteData();
}

export async function GET() {
  try {
    const siteData = await loadSiteData();

    return Response.json(siteData, {
      headers: {
        'Cache-Control': 'public, max-age=60, s-maxage=60, stale-while-revalidate=300',
      },
    });
  } catch (error) {
    console.error('Failed to load site data.', error);

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
