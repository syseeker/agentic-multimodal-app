<script>
  import { onMount } from 'svelte'
  import './app.css'
  import { selectedCase, activeTab, health, chatHistory, pendingPlan, graphElements, evidenceFiles, openEvidence, sentimentData, streamingActive } from './stores.js'
  import { get } from 'svelte/store'
  import CaseSelector from './lib/CaseSelector.svelte'
  import ChatPanel from './lib/ChatPanel.svelte'
  import GraphPanel from './lib/GraphPanel.svelte'
  import EvidenceViewer from './lib/EvidenceViewer.svelte'
  import SentimentPanel from './lib/SentimentPanel.svelte'

  const TABS = [
    { id: 'chat', label: 'Chat' },
    { id: 'graph', label: 'Entity Graph' },
    { id: 'evidence', label: 'Evidence' },
    { id: 'sentiment', label: 'Paralinguistics' },
  ]

  onMount(async () => {
    try {
      const r = await fetch('/api/health')
      health.set(await r.json())
    } catch { /* ignore */ }
  })

  // Track which tab panels are still loading their background data
  let tabLoading = { graph: false, evidence: false, sentiment: false }

  async function onCaseSelect(meta) {
    if (meta.case_id === get(selectedCase)?.case_id) return  // same case, no-op
    if (get(selectedCase)) {
      const ok = confirm(`Switch to case ${meta.case_id}?\n\nThe current conversation will be cleared.`)
      if (!ok) return
    }
    selectedCase.set(meta)
    chatHistory.set([])
    pendingPlan.set(null)
    graphElements.set([])
    evidenceFiles.set([])
    openEvidence.set(null)
    sentimentData.set(null)
    activeTab.set('chat')
    tabLoading = { graph: true, evidence: true, sentiment: true }

    const id = meta.case_id
    fetch(`/api/cases/${id}/graph`).then(r => r.json()).then(d => {
      graphElements.set(d.elements || [])
      tabLoading = { ...tabLoading, graph: false }
    }).catch(() => { tabLoading = { ...tabLoading, graph: false } })

    fetch(`/api/cases/${id}/evidence`).then(r => r.json()).then(d => {
      evidenceFiles.set(d)
      tabLoading = { ...tabLoading, evidence: false }
    }).catch(() => { tabLoading = { ...tabLoading, evidence: false } })

    fetch(`/api/cases/${id}/sentiment`).then(r => r.json()).then(d => {
      sentimentData.set(d)
      tabLoading = { ...tabLoading, sentiment: false }
    }).catch(() => { tabLoading = { ...tabLoading, sentiment: false } })
  }

  $: caseId = $selectedCase?.case_id

  const TAB_STORE_KEY = { graph: 'graph', evidence: 'evidence', sentiment: 'sentiment' }
</script>

<div class="shell">
  <!-- Header -->
  <header class="header">
    <div class="logo">
      <span class="logo-icon">&#128270;</span>
      <span class="logo-text">Sherlock</span>
      <span class="logo-sub">Forensic Case Workbench</span>
    </div>
    {#if $selectedCase}
      <div class="case-badge">
        <span class="badge blue mono">{$selectedCase.case_id}</span>
        <span class="case-meta">
          {$selectedCase.case_type ?? ''} &middot; {$selectedCase.district ?? ''}
        </span>
        {#if $selectedCase.case_status}
          <span class="badge {$selectedCase.case_status === 'closed' ? 'green' : 'amber'}">
            {$selectedCase.case_status.replace('_', ' ')}
          </span>
        {/if}
      </div>
    {/if}
    <div class="health-dots">
      <span class="dot" class:ok={$health.aiq} class:err={$health.aiq === false} title="AI-Q">AI-Q</span>
      <span class="dot" class:ok={$health.neo4j} class:err={$health.neo4j === false} title="Neo4j">Graph</span>
    </div>
  </header>

  <!-- Body: sidebar + main -->
  <div class="body">
    <aside class="sidebar">
      <CaseSelector on:select={e => onCaseSelect(e.detail)} />
    </aside>

    <main class="main">
      {#if !$selectedCase}
        <div class="empty-state">
          <div class="empty-icon">&#128269;</div>
          <div class="empty-title">Select a case to begin</div>
          <div class="empty-sub">Choose a case from the left panel to open the investigation workbench.</div>
        </div>
      {:else}
        <!-- Tab bar -->
        <nav class="tabs">
          {#each TABS as tab}
            <button
              class="tab-btn"
              class:active={$activeTab === tab.id}
              on:click={() => activeTab.set(tab.id)}
            >
              {tab.label}
              {#if tabLoading[tab.id]}
                <span class="tab-dot" title="Loading…"></span>
              {/if}
            </button>
          {/each}
        </nav>

        <!-- Tab content -->
        <div class="panel">
          {#if $activeTab === 'chat'}
            <ChatPanel caseId={caseId} caseMeta={$selectedCase} />
          {:else if $activeTab === 'graph'}
            <GraphPanel caseId={caseId} />
          {:else if $activeTab === 'evidence'}
            <EvidenceViewer caseId={caseId} />
          {:else if $activeTab === 'sentiment'}
            <SentimentPanel caseId={caseId} />
          {/if}
        </div>
      {/if}
    </main>
  </div>
</div>

<style>
  .shell {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }

  /* Header */
  .header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 20px;
    height: 52px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .logo {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .logo-icon { font-size: 20px; }
  .logo-text { font-size: 16px; font-weight: 700; color: var(--accent); letter-spacing: -0.3px; }
  .logo-sub { font-size: 12px; color: var(--text-muted); }

  .case-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: 8px;
    padding-left: 16px;
    border-left: 1px solid var(--border);
  }
  .case-meta { font-size: 12px; color: var(--text-2); text-transform: capitalize; }

  .health-dots {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-left: auto;
    font-size: 11px;
    color: var(--text-muted);
  }
  .dot { display: flex; align-items: center; gap: 4px; }
  .dot::before {
    content: '';
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--border);
  }
  .dot.ok::before { background: var(--ok); }
  .dot.err::before { background: var(--danger); }

  /* Body layout */
  .body {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  .sidebar {
    width: 240px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
    overflow-y: auto;
    background: var(--surface);
  }

  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--bg);
  }

  .panel {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  /* Empty state */
  .empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: var(--text-muted);
  }
  .empty-icon { font-size: 48px; opacity: 0.4; }
  .empty-title { font-size: 18px; font-weight: 600; color: var(--text-2); }
  .empty-sub { font-size: 13px; max-width: 300px; text-align: center; line-height: 1.6; }
</style>
