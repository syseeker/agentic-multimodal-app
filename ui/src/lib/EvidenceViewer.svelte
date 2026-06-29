<script>
  import { onMount } from 'svelte'
  import { evidenceFiles, openEvidence } from '../stores.js'

  export let caseId

  let loadingFiles = false
  let loadingContent = false
  let error = null

  // openEvidence store holds: { name, subpath, type, content?, url?, error? }

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

  async function openFile(f) {
    loadingContent = true
    openEvidence.set(null)

    try {
      if (f.type === 'text') {
        const r = await fetch(`/api/cases/${caseId}/evidence/${encodeURIComponent(f.subpath)}`)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const d = await r.json()
        openEvidence.set({ ...f, content: d.content })
      } else {
        // Audio / image / video — build a direct URL; browser streams it
        openEvidence.set({
          ...f,
          url: `/api/cases/${caseId}/media/${f.subpath}`,
        })
      }
    } catch (e) {
      openEvidence.set({ ...f, content: `Error: ${e.message}`, type: 'text', error: true })
    } finally {
      loadingContent = false
    }
  }

  const TYPE_ICONS = { audio: '🎙️', image: '🖼️', video: '🎬', text: '📄' }
  const NAMED_ICONS = {
    'case_report.txt': '📋',
    'witness_statement.txt': '🗣️',
    'lab_report.txt': '🧪',
    'whatsapp_chat.txt': '💬',
    'audio_analysis.txt': '🎙️',
    'metadata.json': '🔖',
  }
  function icon(f) { return NAMED_ICONS[f.name] ?? TYPE_ICONS[f.type] ?? '📄' }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  // Group file list by type section
  $: grouped = groupFiles($evidenceFiles)
  function groupFiles(files) {
    const sections = [
      { label: 'Documents', types: ['text'], files: [] },
      { label: 'Audio',     types: ['audio'], files: [] },
      { label: 'Images',    types: ['image'], files: [] },
      { label: 'Video',     types: ['video'], files: [] },
    ]
    for (const f of files) {
      for (const s of sections) {
        if (s.types.includes(f.type)) { s.files.push(f); break }
      }
    }
    return sections.filter(s => s.files.length > 0)
  }
</script>

<div class="evidence-panel">
  <!-- File list -->
  <div class="file-list">
    <div class="list-header">Evidence Files</div>
    {#if loadingFiles}
      <div class="state loading"><span class="spinner sm"></span> Loading…</div>
    {:else if error}
      <div class="state err">{error}</div>
    {:else if $evidenceFiles.length === 0}
      <div class="state muted">No files found.</div>
    {:else}
      {#each grouped as section}
        <div class="section-label">{section.label}</div>
        {#each section.files as f}
          <button
            class="file-item"
            class:active={$openEvidence?.subpath === f.subpath}
            on:click={() => openFile(f)}
          >
            <span class="file-icon">{icon(f)}</span>
            <span class="file-name">{f.name}</span>
            <span class="file-size muted">{formatSize(f.size)}</span>
          </button>
        {/each}
      {/each}
    {/if}
  </div>

  <!-- Content / media viewer -->
  <div class="file-content">
    {#if loadingContent}
      <div class="content-state loading"><span class="spinner"></span> Loading…</div>
    {:else if !$openEvidence}
      <div class="content-state muted">Select a file to view.</div>
    {:else}
      <div class="content-header">
        <span>{icon($openEvidence)} {$openEvidence.name}</span>
        {#if $openEvidence.url}
          <a class="dl-link" href={$openEvidence.url} download={$openEvidence.name}>⬇ Download</a>
        {/if}
      </div>

      {#if $openEvidence.type === 'audio'}
        <div class="media-wrapper">
          <audio controls src={$openEvidence.url} class="audio-player">
            Your browser does not support audio playback.
          </audio>
          <div class="media-meta muted">{$openEvidence.name} · {formatSize($openEvidence.size)}</div>
        </div>

      {:else if $openEvidence.type === 'image'}
        <div class="media-wrapper">
          <img
            src={$openEvidence.url}
            alt={$openEvidence.name}
            class="image-viewer"
          />
          <div class="media-meta muted">{$openEvidence.name} · {formatSize($openEvidence.size)}</div>
        </div>

      {:else if $openEvidence.type === 'video'}
        <div class="media-wrapper video-wrapper">
          <!-- svelte-ignore a11y-media-has-caption -->
          <video controls src={$openEvidence.url} class="video-player">
            Your browser does not support video playback.
          </video>
          <div class="media-meta muted">{$openEvidence.name} · {formatSize($openEvidence.size)}</div>
        </div>

      {:else}
        <pre class="content-body" class:err={$openEvidence.error}>{$openEvidence.content}</pre>
      {/if}
    {/if}
  </div>
</div>

<style>
  .evidence-panel {
    display: flex;
    height: 100%;
    overflow: hidden;
  }

  /* ── Sidebar ── */
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
    flex-shrink: 0;
  }

  .section-label {
    padding: 8px 14px 3px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    opacity: 0.6;
  }

  .state { padding: 16px 14px; font-size: 13px; color: var(--text-muted); }
  .state.err { color: var(--danger); }

  .file-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
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

  .file-icon { font-size: 15px; flex-shrink: 0; }
  .file-name { font-size: 12px; color: var(--text); flex: 1; word-break: break-all; }
  .file-size { font-size: 10px; }

  /* ── Main viewer ── */
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
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .dl-link {
    font-size: 11px;
    color: var(--accent);
    text-decoration: none;
    padding: 2px 8px;
    border: 1px solid var(--accent-dim);
    border-radius: var(--radius);
    font-weight: 500;
  }
  .dl-link:hover { background: var(--accent-dim); }

  /* ── Text viewer ── */
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
    margin: 0;
  }
  .content-body.err { color: var(--danger); }

  /* ── Media wrappers ── */
  .media-wrapper {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 24px;
    overflow: auto;
    background: #0a0c10;
  }

  .video-wrapper {
    justify-content: flex-start;
    padding: 16px;
  }

  .audio-player {
    width: 100%;
    max-width: 560px;
    accent-color: var(--accent);
  }

  .image-viewer {
    max-width: 100%;
    max-height: calc(100% - 40px);
    object-fit: contain;
    border-radius: 4px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.6);
  }

  .video-player {
    width: 100%;
    max-height: calc(100vh - 200px);
    background: #000;
    border-radius: 4px;
  }

  .media-meta {
    font-size: 11px;
  }
</style>
