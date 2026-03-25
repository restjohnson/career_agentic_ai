const API = '/api';

function normalizeErrorDetail(detail, fallbackMessage = 'Request failed') {
  const raw = typeof detail === 'string' ? detail.trim() : '';
  if (!raw) return fallbackMessage;

  // Hide backend/provider internals and show actionable UI-safe messages.
  if (
    raw.includes('httpx.RemoteProtocolError')
    || raw.includes('RemoteProtocolError')
    || raw.includes('Server disconnected')
  ) {
    return 'Temporary connection issue while processing your request. Please try again.';
  }

  if (raw.includes('ReadTimeout') || raw.includes('TimeoutError')) {
    return 'The request timed out. Please try again.';
  }

  return raw;
}

async function getErrorDetail(res, fallbackMessage) {
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const payload = await res.json().catch(() => null);
    if (payload && typeof payload.detail === 'string' && payload.detail.trim()) {
      return normalizeErrorDetail(payload.detail, `${fallbackMessage}: ${res.status}`);
    }
  }

  const text = await res.text().catch(() => '');
  if (text && text.trim()) {
    return normalizeErrorDetail(text.trim(), `${fallbackMessage}: ${res.status}`);
  }

  return `${fallbackMessage}: ${res.status}`;
}

export async function startSession() {
  const res = await fetch(`${API}/session/start`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(await getErrorDetail(res, 'Session start failed'));
  }
  return res.json(); // { session_token, session_id }
}

export async function uploadEvidence(sessionToken, file, sourceType = 'resume', consentLevel = 'derived_only') {
  const form = new FormData();
  form.append('source_type', sourceType);
  form.append('consent_level', consentLevel);
  form.append('file', file);
  const res = await fetch(`${API}/evidence`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${sessionToken}` },
    body: form,
  });
  if (!res.ok) {
    throw new Error(await getErrorDetail(res, 'Evidence upload failed'));
  }
  return res.json(); // { document_id, content_hash, storage_ref, source_type }
}

export async function createRun(sessionToken, desiredRole, evidenceDocumentIds, rawUserText = null) {
  const res = await fetch(`${API}/runs`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${sessionToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      desired_role: desiredRole,
      raw_user_text: rawUserText,
      evidence_document_ids: evidenceDocumentIds,
    }),
  });
  if (!res.ok) {
    throw new Error(await getErrorDetail(res, 'Run failed'));
  }
  return res.json(); // { run_id, status }
}

/**
 * Subscribe to real-time agent step events via SSE.
 * @param {string} sessionToken
 * @param {string} runId
 * @param {(event: {type: string, step?: string, final_state?: object, detail?: string}) => void} onEvent
 * @returns {() => void} cleanup function to close the stream
 */
export function streamRun(sessionToken, runId, onEvent) {
  const url = `${API}/runs/${runId}/stream?token=${encodeURIComponent(sessionToken)}`;
  const evtSource = new EventSource(url);
  let streamClosed = false;

  evtSource.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      if (event?.type === 'error') {
        event.detail = normalizeErrorDetail(event.detail, 'Something went wrong while processing your request.');
      }
      onEvent(event);
      if (event.type === 'done' || event.type === 'error') {
        streamClosed = true;
        evtSource.close();
      }
    } catch {
      // ignore malformed events
    }
  };

  evtSource.onerror = () => {
    // EventSource auto-reconnects for transient network/server restarts.
    // Only emit an error when the stream is permanently closed.
    if (!streamClosed && evtSource.readyState === EventSource.CLOSED) {
      onEvent({ type: 'error', detail: normalizeErrorDetail('Connection to server lost', 'Connection to server lost') });
      streamClosed = true;
      evtSource.close();
    }
  };

  return () => {
    streamClosed = true;
    evtSource.close();
  };
}
