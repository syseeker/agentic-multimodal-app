<script>
  import { onMount } from 'svelte'
  import { evidenceFiles, openEvidence } from '../stores.js'

  export let caseId

  let loadingFiles = false
  let loadingContent = false
  let error = null

  onMount(async () => {
    if ($evidenceFiles.length === 0) {
      loadingFiles = true
      try {
        const r = await fetch(`/api/cases/${caseId}/evidence`)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        evidenceFiles.set(await r.json())
      } catch (e) {
        error = e.message
      } finally {
        loadingFiles = false
      }
    }
  })

  async function openFile(name) {
    loadingContent = true
    openEvidence.set(null)
    try {
      const r = await fetch(`/api/cases/${caseId}/evidence/${encodeURIComponent(name)}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      openEvidence.set(d)
    } catch (e) {
      openEvidence.set({ filename: name, content: `Error: ${e.message}`, error: true })
    } finally {
      loadingContent = false
    }
  }

  const FILE_ICONS = {
    'case_report.txt': '📋',
    'witness_statement.txt': '🗣️',
    'lab_report.txt': '🧪',
    'whatsapp_chat.txt': '💬',
    'audio_analysis.txt': '🎙️',
    'metadata.json': '🔖',
  }
  function icon(name) { return FILE_ICONS[name] ?? '📄' }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`
    return `${(bytes / 1024).toFixed(1)} KB`
  }
</script>

<div class="evidence-panel">
  <!-- File list -->
  <div class="file-list">
    <div class="list-header">Evidence Files</div>
    {#if loadingFiles}
      <div class="state">Loading...</div>
    {:else if error}
      <div class="state err">{error}</div>
    {:else if $evidenceFiles.length === 0}
      <div class="state muted">No files found.</div>
    {:else}
      {#each $evidenceFiles as f}
        <button
          class="file-item"
          class:active={$openEvidence?.filename === f.name}
          on:click={() => openFile(f.name)}
        >
          <span class="file-icon">{icon(f.name)}</span>
          <span class="file-name">{f.name}</span>
          <span class="file-size muted">{formatSize(f.size)}</span>
        </button>
      {/each}
    {/if}
  </div>

  <!-- File content viewer -->
  <div class="file-content">
    {#if loadingContent}
      <div class="content-state">Loading...</div>
    {:else if !$openEvidence}
      <div class="content-state muted">Select a file to view its contents.</div>
    {:else}
      <div class="content-header">
        <span>{icon($openEvidence.filename)} {$openEvidence.filename}</span>
      </div>
      <pre class="content-body" class:err={$openEvidence.error}>{$openEvidence.content}</pre>
    {/if}
  </div>
</div>

<style>
  .evidence-panel {
    display: flex;
    height: 100%;
    overflow: hidden;
  }

  .file-list {
    width: 220px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    background: var(--surface);
  }

  .list-header {
    padding: 12px 14px 6px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
  }

  .state { padding: 16px 14px; font-size: 13px; color: var(--text-muted); }
  .state.err { color: var(--danger); }

  .file-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    text-align: left;
    transition: background 0.1s;
    width: 100%;
  }
  .file-item:hover { background: var(--surface-2); }
  .file-item.active { background: var(--surface-2); border-left: 3px solid var(--accent); }

  .file-icon { font-size: 16px; flex-shrink: 0; }
  .file-name { font-size: 12px; color: var(--text); flex: 1; word-break: break-all; }
  .file-size { font-size: 10px; }

  .file-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .content-state {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    color: var(--text-muted);
  }

  .content-header {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    font-weight: 600;
    background: var(--surface);
    flex-shrink: 0;
  }

  .content-body {
    flex: 1;
    overflow: auto;
    padding: 16px;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text);
  }
  .content-body.err { color: var(--danger); }
</style>
