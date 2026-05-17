function inferStatusTone(message) {
  const text = String(message || '').trim();
  if (!text) return '';
  if (/(^|\b)(could not|failed|error|invalid|unavailable|not found|timed out|missing)(\b|$)/i.test(text)) {
    return 'error';
  }
  if (/(^|\b)(no |select |choose |warning|still in use|skipped)(\b|$)/i.test(text)) {
    return 'warning';
  }
  if (/(^|\b)(saved|created|deleted|updated|uploaded|added|generated|imported|cleared|complete|completed|ready|removed|reset|moved)(\b|$)/i.test(text)) {
    return 'success';
  }
  return 'info';
}

function applyStatus(element, message, tone = '') {
  if (!element) return;
  const text = String(message || '').trim();
  element.textContent = text;
  if (!text) {
    element.hidden = true;
    delete element.dataset.tone;
    return;
  }
  element.hidden = false;
  element.dataset.tone = tone || inferStatusTone(text);
}

export {applyStatus, inferStatusTone};
