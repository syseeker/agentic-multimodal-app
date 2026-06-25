<script>
  import { api } from '$lib/api.js';
  import GraphView from '$lib/GraphView.svelte';

  let caseId = 'sample-case';
  let objective = 'Map the parties, their relationships, and the sentiment of the seized statement.';
  let loadDir = 'data/sample_case';

  let phase = 'idle'; // idle | planned | investigated | done
  let plan = null;
  let approved = {}; // asset_id -> bool
  let log = [];
  let graph = { nodes: [], edges: [] };
  let report = null;
  let busy = false;
  let error = '';

  // chat
  let chatMsg = '';
  let chat = [];

  async function guard(fn) {
    busy = true; error = '';
    try { await fn(); } catch (e) { error = e.message; } finally { busy = false; }
  }

  const createAndPlan = () => guard(async () => {
    await api.createCase({ case_id: caseId, objective, load_dir: loadDir });
    plan = await api.plan(caseId);
    approved = Object.fromEntries(plan.steps.map((s) => [s.asset_id, true]));
    phase = 'planned';
    log = (await api.log(caseId)).log;
  });

  const runInvestigation = () => guard(async () => {
    const ids = plan.steps.map((s) => s.asset_id).filter((id) => approved[id]);
    await api.investigate(caseId, ids);
    graph = await api.graph(caseId);
    log = (await api.log(caseId)).log;
    phase = 'investigated';
  });

  const finalize = () => guard(async () => {
    report = await api.finalize(caseId);
    log = (await api.log(caseId)).log;
    phase = 'done';
  });

  const send = () => guard(async () => {
    if (!chatMsg.trim()) return;
    const msg = chatMsg; chatMsg = '';
    chat = [...chat, { role: 'user', content: msg }];
    const { answer } = await api.chat(caseId, msg, chat);
    chat = [...chat, { role: 'assistant', content: answer }];
  });
</script>

<main>
  <header>
    <h1>🦉 Sherlock <span>· agentic multimodal investigation</span></h1>
    <p class="sub">Human-in-the-loop: approve each phase. Every claim is cited.</p>
  </header>

  {#if error}<div class="err">{error}</div>{/if}

  <section class="card">
    <h2>Case</h2>
    <label>Case ID <input bind:value={caseId} /></label>
    <label>Objective <textarea bind:value={objective} rows="2"></textarea></label>
    <label>Load dir <input bind:value={loadDir} /></label>
    <button on:click={createAndPlan} disabled={busy}>1 · Plan</button>
  </section>

  {#if plan}
    <section class="card">
      <h2>Plan <small>(Planner) — approve assets to process</small></h2>
      <p>{plan.objective}</p>
      <ul class="plan">
        {#each plan.steps as s}
          <li>
            <label>
              <input type="checkbox" bind:checked={approved[s.asset_id]} />
              <b>{s.asset_id}</b> <em>[{s.modality}]</em> — {s.action}
            </label>
            {#if s.rationale}<div class="why">{s.rationale}</div>{/if}
          </li>
        {/each}
      </ul>
      <button on:click={runInvestigation} disabled={busy || phase === 'idle'}>
        2 · Approve & Investigate
      </button>
    </section>
  {/if}

  {#if phase === 'investigated' || phase === 'done'}
    <section class="card">
      <h2>Relationship graph <small>(FalkorDB + cuGraph)</small></h2>
      <GraphView {graph} keyPlayers={report?.graph?.key_players || []} />
      <button on:click={finalize} disabled={busy}>3 · Synthesize report (Critic)</button>
    </section>
  {/if}

  {#if report}
    <section class="card">
      <h2>Case report <small>(Critic)</small></h2>
      <p class="summary">{report.summary}</p>
      {#if report.graph?.key_players?.length}
        <p><b>Key players:</b> {report.graph.key_players.map((k) => k.id).join(', ')}</p>
      {/if}
      {#if report.sentiments?.length}
        <p><b>Sentiment:</b>
          {#each report.sentiments as s}<span class="chip">{s.asset_id}: {s.label} ({s.score})</span>{/each}
        </p>
      {/if}
      <p class="cites"><b>Citations:</b> {report.citations.join(', ')}</p>
    </section>

    <section class="card">
      <h2>Ask Sherlock</h2>
      <div class="chat">
        {#each chat as m}<div class="msg {m.role}"><b>{m.role}</b>: {m.content}</div>{/each}
      </div>
      <div class="row">
        <input bind:value={chatMsg} placeholder="Who transferred money to whom?"
               on:keydown={(e) => e.key === 'Enter' && send()} />
        <button on:click={send} disabled={busy}>Send</button>
      </div>
    </section>
  {/if}

  {#if log.length}
    <section class="card">
      <h2>Agent trace</h2>
      <ol class="log">
        {#each log as l}<li><b>{l.phase}</b> — {l.message} <code>{JSON.stringify(l.detail)}</code></li>{/each}
      </ol>
    </section>
  {/if}
</main>

<style>
  :global(body) { margin: 0; background: #0e0f12; color: #e8eaed;
    font-family: ui-sans-serif, system-ui, sans-serif; }
  main { max-width: 880px; margin: 0 auto; padding: 24px; }
  header h1 { margin: 0; color: #76b900; }
  header h1 span, .sub { color: #9aa0a6; font-weight: 400; font-size: 0.6em; }
  .sub { font-size: 0.85rem; }
  .card { background: #16181d; border: 1px solid #24262c; border-radius: 10px;
    padding: 16px 18px; margin: 16px 0; }
  h2 { margin: 0 0 10px; font-size: 1.05rem; }
  h2 small { color: #9aa0a6; font-weight: 400; }
  label { display: block; margin: 8px 0; font-size: 0.85rem; color: #c0c4cc; }
  input, textarea { width: 100%; background: #0e0f12; color: #e8eaed;
    border: 1px solid #2a2d34; border-radius: 6px; padding: 8px; box-sizing: border-box; }
  input[type=checkbox] { width: auto; }
  button { background: #76b900; color: #0e0f12; border: 0; border-radius: 6px;
    padding: 9px 16px; font-weight: 600; cursor: pointer; margin-top: 8px; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .plan { list-style: none; padding: 0; }
  .plan li { padding: 6px 0; border-bottom: 1px solid #24262c; }
  .why { color: #9aa0a6; font-size: 0.8rem; margin-left: 24px; }
  .chip { background: #24262c; border-radius: 12px; padding: 2px 10px; margin-right: 6px; font-size: 0.8rem; }
  .summary { line-height: 1.5; }
  .cites { color: #9aa0a6; font-size: 0.85rem; }
  .chat { max-height: 260px; overflow: auto; margin-bottom: 10px; }
  .msg { padding: 6px 0; border-bottom: 1px solid #1d1f25; }
  .msg.assistant b { color: #76b900; }
  .row { display: flex; gap: 8px; }
  .log { color: #c0c4cc; font-size: 0.82rem; }
  .log code { color: #76b900; }
  .err { background: #3a1014; border: 1px solid #ef476f; color: #ffb3c0;
    padding: 10px; border-radius: 8px; }
</style>
