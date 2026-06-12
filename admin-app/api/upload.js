import { put } from '@vercel/blob';

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

function getExtension(file) {
  const rawName = String(file?.name ?? '');
  const nameParts = rawName.split('.');
  if (nameParts.length > 1) {
    return nameParts.pop().toLowerCase();
  }

  const type = String(file?.type ?? '');
  if (type.includes('/')) {
    return type.split('/')[1].toLowerCase();
  }

  return 'png';
}

export async function POST(request) {
  try {
    if (!hasBlobConfig()) {
      return Response.json(
        {
          error: 'Blob storage is not configured. Connect a public Blob store to this Vercel project first.',
        },
        { status: 500, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    const formData = await request.formData();
    const file = formData.get('file');
    const kind = formData.get('kind') === 'avatar' ? 'avatar' : 'song';
    const slug = slugify(formData.get('slug') || `${kind}-${Date.now()}`) || `${kind}-${Date.now()}`;

    if (!file || typeof file.arrayBuffer !== 'function') {
      return Response.json(
        { error: 'Please choose an image to upload.' },
        { status: 400, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    if (file.type && !file.type.startsWith('image/')) {
      return Response.json(
        { error: 'Only image uploads are supported.' },
        { status: 400, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    const pathname = `images/${kind}/${slug}-${Date.now()}.${getExtension(file)}`;
    const blob = await put(pathname, file, {
      access: 'public',
      contentType: file.type || undefined,
      cacheControlMaxAge: 31536000,
    });

    return Response.json(
      {
        ok: true,
        url: blob.url,
        pathname: blob.pathname,
      },
      {
        headers: {
          'Cache-Control': 'no-store',
        },
      },
    );
  } catch (error) {
    console.error('Failed to upload image.', error);
    return Response.json(
      { error: error instanceof Error ? error.message : 'Failed to upload image.' },
      {
        status: 400,
        headers: {
          'Cache-Control': 'no-store',
        },
      },
    );
  }
}
