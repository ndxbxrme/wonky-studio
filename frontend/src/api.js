const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

async function apiFetch(path, options = {}) {
  const response = await fetch(resolveApiPath(path), {
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
  return resolveApiPath(`/api/uploads/files/${uploadedFileId}/content`);
}

function apiUrl(path) {
  return new URL(resolveApiPath(path), window.location.origin).toString();
}

function objectMaskUrl(maskId, variant, cacheKey = '') {
  const url = new URL(resolveApiPath(`/api/object-masks/${maskId}/${variant}`), window.location.origin);
  if (cacheKey) url.searchParams.set('v', cacheKey);
  return url.toString();
}

function objectThumbnailUrl(objectId, cacheKey = '') {
  const url = new URL(resolveApiPath(`/api/scene-objects/${objectId}/thumbnail`), window.location.origin);
  if (cacheKey) url.searchParams.set('v', cacheKey);
  return url.toString();
}

function scriptAudioCandidateUrl(candidateId) {
  return resolveApiPath(`/api/script-audio-candidates/${candidateId}/content`);
}

function resolveApiPath(path) {
  if (!path.startsWith('/')) path = `/${path}`;
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path;
}

export {
  API_BASE_URL,
  apiUrl,
  apiFetch,
  objectMaskUrl,
  objectThumbnailUrl,
  scriptAudioCandidateUrl,
  uploadedFileUrl
};
