// Thin client for the agent API. The browser hits the published app port.
import { env } from '$env/dynamic/public';

const BASE = env.PUBLIC_API_URL || 'http://localhost:8000';

async function post(path, body) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json();
}

async function get(path) {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const api = {
  health: () => get('/health'),
  createCase: (body) => post('/cases', body),
  plan: (id) => post(`/cases/${id}/plan`),
  investigate: (id, approved) => post(`/cases/${id}/investigate`, { approved_asset_ids: approved }),
  finalize: (id) => post(`/cases/${id}/finalize`),
  graph: (id) => get(`/cases/${id}/graph`),
  log: (id) => get(`/cases/${id}/log`),
  chat: (id, message, history) => post(`/cases/${id}/chat`, { message, history })
};
