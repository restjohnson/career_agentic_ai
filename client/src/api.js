const API = '/api';

export async function startSession() {
  const res = await fetch(`${API}/session/start`, { method: 'POST' });
  if (!res.ok) throw new Error(`Session start failed: ${res.status}`);
  return res.json(); // { session_token, session_id }
}

export async function uploadEvidence(sessionToken, file, sourceType = 'resume') {
  const form = new FormData();
  form.append('source_type', sourceType);
  form.append('file', file);
  const res = await fetch(`${API}/evidence`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${sessionToken}` },
    body: form,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Evidence upload failed: ${res.status}`);
  }
  return res.json(); // { document_id, content_hash, storage_ref, source_type }
}

export async function createRun(sessionToken, desiredRole, evidenceDocumentIds, rawUserText = null, studentConstraints = null) {
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
      ...(studentConstraints && { student_constraints: studentConstraints }),
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Run failed: ${res.status}`);
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

  evtSource.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      onEvent(event);
      if (event.type === 'done' || event.type === 'error') {
        evtSource.close();
      }
    } catch {
      // ignore malformed events
    }
  };

  evtSource.onerror = () => {
    onEvent({ type: 'error', detail: 'Connection to server lost' });
    evtSource.close();
  };

  return () => evtSource.close();
}
