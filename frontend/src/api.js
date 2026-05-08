const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : {'Content-Type': 'application/json'}),
      ...(options.headers ?? {})
    }
  });
  if (!response.ok) {
    const error = new Error(`API request failed: ${response.status}`);
    error.response = response;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

function uploadedFileUrl(uploadedFileId) {
  return `${API_BASE_URL}/api/uploads/files/${uploadedFileId}/content`;
}

function objectMaskUrl(maskId, variant, cacheKey = '') {
  const url = new URL(`/api/object-masks/${maskId}/${variant}`, API_BASE_URL);
  if (cacheKey) url.searchParams.set('v', cacheKey);
  return url.toString();
}

function objectThumbnailUrl(objectId, cacheKey = '') {
  const url = new URL(`/api/scene-objects/${objectId}/thumbnail`, API_BASE_URL);
  if (cacheKey) url.searchParams.set('v', cacheKey);
  return url.toString();
}

export {API_BASE_URL, apiFetch, objectMaskUrl, objectThumbnailUrl, uploadedFileUrl};
