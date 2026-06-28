<script>
  import { createEventDispatcher } from 'svelte'

  const dispatch = createEventDispatcher()

  let open = false
  let files = []
  let caseType = 'unknown'
  let district = ''
  let suspectName = ''
  let assignedOfficer = ''
  let uploading = false
  let result = null
  let error = null

  const CASE_TYPES = ['homicide', 'fraud', 'robbery', 'trafficking', 'cybercrime', 'assault', 'unknown']

  function onFileChange(e) {
    files = Array.from(e.target.files)
  }

  async function submit() {
    if (files.length === 0) { error = 'Select at least one file.'; return }
    uploading = true
    error = null
    result = null

    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    fd.append('case_type', caseType)
    fd.append('district', district)
    fd.append('suspect_name', suspectName)
    fd.append('assigned_officer', assignedOfficer)

    try {
      const r = await fetch('/api/cases/upload', { method: 'POST', body: fd })
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`)
      result = await r.json()
      // Notify parent so case list can refresh and new case can auto-select
      dispatch('uploaded', { case_id: result.case_id })
    } catch (e) {
      error = e.message
    } finally {
      uploading = false
    }
  }

  function close() {
    open = false
    files = []
    result = null
    error = null
  }
</script>

<!-- Toggle button shown in sidebar -->
<button class="upload-trigger btn ghost" on:click={() => open = true}>
  + Upload Case
</button>

<!-- Modal -->
{#if open}
  <div class="modal-backdrop" on:click|self={close}>
    <div class="modal">
      <div class="modal-header">
        <strong>Upload New Case</strong>
        <button class="btn ghost" on:click={close} style="padding:2px 8px">✕</button>
      </div>

      {#if result}
        <div class="success">
          <div class="success-icon">✅</div>
          <div class="success-id mono">{result.case_id}</div>

          <!-- File counts by type -->
          <div class="type-counts">
            {#if result.file_counts?.text > 0}
              <span class="type-chip text-chip">📄 {result.file_counts.text} text</span>
            {/if}
            {#if result.file_counts?.audio > 0}
              <span class="type-chip audio-chip">🎙️ {result.file_counts.audio} audio</span>
            {/if}
            {#if result.file_counts?.image > 0}
              <span class="type-chip image-chip">🖼️ {result.file_counts.image} image</span>
            {/if}
            {#if result.file_counts?.video > 0}
              <span class="type-chip video-chip">🎬 {result.file_counts.video} video</span>
            {/if}
          </div>

          <!-- Pipeline status -->
          {#if result.pipelines_triggered?.length > 0}
            <div class="pipeline-list">
              <div class="pipeline-title">Pipelines triggered</div>
              {#each result.pipelines_triggered as p}
                <div class="pipeline-item">
                  <span class="pipeline-dot {p.includes('stub') || p.includes('pending') ? 'pending' : 'running'}">●</span>
                  <span class="pipeline-label">{
                    p === 'rag_ingest' ? 'Text → RAG vector store' :
                    p === 'entity_extraction' ? 'Entity extraction → graph (background)' :
                    p === 'audio_asr' ? 'Audio → Parakeet ASR → transcript (background)' :
                    p === 'image_caption_stub' ? 'Images → VLM captioning (GPU required)' :
                    p === 'video_vss_pending_gpu' ? 'Video → VSS ingestion (GPU required)' :
                    p
                  }</span>
                </div>
              {/each}
            </div>
          {/if}

          <div class="success-files">
            {#each result.files_saved as f}
              <span class="badge {
                f.type === 'audio' ? 'amber' :
                f.type === 'image' ? 'green' :
                f.type === 'video' ? 'purple' : 'blue'
              }">{f.name}</span>
            {/each}
          </div>
          <button class="btn primary" on:click={close} style="margin-top:12px">Done</button>
        </div>
      {:else}
        <div class="modal-body">
          <!-- File picker: folder or individual files -->
          <div class="field">
            <label>Evidence files</label>
            <div class="file-zone" class:has-files={files.length > 0}>
              <!-- hidden inputs: one for folder, one for individual files -->
              <input type="file" multiple webkitdirectory on:change={onFileChange}
                style="display:none" id="file-folder" />
              <input type="file" multiple accept="*" on:change={onFileChange}
                style="display:none" id="file-single" />

              {#if files.length === 0}
                <div class="file-label">
                  <div class="pick-row">
                    <label for="file-folder" class="pick-btn">📁 Select folder</label>
                    <span class="pick-or">or</span>
                    <label for="file-single" class="pick-btn">🗂️ Individual files</label>
                  </div>
                  <div class="pick-hint">Supports text, PDF, audio, image, video</div>
                </div>
              {:else}
                <div class="file-label">
                  <div class="pick-row">
                    <label for="file-folder" class="pick-btn">📁 Change folder</label>
                    <span class="pick-or">or</span>
                    <label for="file-single" class="pick-btn">🗂️ Add files</label>
                  </div>
                  <div class="file-names">
                    {#each files.slice(0, 8) as f}
                      <span class="badge blue">{f.name}</span>
                    {/each}
                    {#if files.length > 8}
                      <span class="muted">+{files.length - 8} more</span>
                    {/if}
                  </div>
                </div>
              {/if}
            </div>
          </div>

          <div class="fields-row">
            <div class="field">
              <label>Case type</label>
              <select bind:value={caseType}>
                {#each CASE_TYPES as t}
                  <option value={t}>{t}</option>
                {/each}
              </select>
            </div>
            <div class="field">
              <label>District</label>
              <input type="text" bind:value={district} placeholder="e.g. Jurong East" />
            </div>
          </div>

          <div class="fields-row">
            <div class="field">
              <label>Suspect name (if known)</label>
              <input type="text" bind:value={suspectName} placeholder="optional" />
            </div>
            <div class="field">
              <label>Assigned officer</label>
              <input type="text" bind:value={assignedOfficer} placeholder="optional" />
            </div>
          </div>

          {#if error}
            <div class="err-msg">{error}</div>
          {/if}
        </div>

        <div class="modal-footer">
          <button class="btn ghost" on:click={close} disabled={uploading}>Cancel</button>
          <button class="btn primary" on:click={submit} disabled={uploading || files.length === 0}>
            {uploading ? 'Uploading...' : 'Create Case'}
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .upload-trigger {
    width: 100%;
    justify-content: center;
    border-top: 1px solid var(--border);
    border-radius: 0;
    padding: 10px;
    font-size: 12px;
    color: var(--accent);
    margin-top: auto;
  }
  .upload-trigger:hover { background: var(--surface-2); }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    z-index: 100;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .modal {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    width: 500px;
    max-width: 95vw;
    max-height: 90vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 15px;
  }

  .modal-body {
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding: 14px 20px;
    border-top: 1px solid var(--border);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 5px;
    flex: 1;
  }
  label { font-size: 12px; color: var(--text-muted); font-weight: 500; }

  .fields-row { display: flex; gap: 12px; }

  select {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    padding: 7px 10px;
    font-size: 13px;
    outline: none;
  }
  select:focus { border-color: var(--accent); }

  .file-zone {
    border: 2px dashed var(--border);
    border-radius: var(--radius);
    transition: border-color 0.15s;
  }
  .file-zone.has-files { border-color: var(--accent-dim); }
  .file-zone:hover { border-color: var(--accent); }

  .file-label {
    display: block;
    padding: 14px 16px;
    font-size: 13px;
    color: var(--text-2);
    text-align: center;
  }

  .pick-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }
  .pick-btn {
    cursor: pointer;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 5px 12px;
    font-size: 12px;
    color: var(--text);
    transition: border-color 0.15s;
  }
  .pick-btn:hover { border-color: var(--accent); color: var(--accent); }
  .pick-or { font-size: 11px; color: var(--text-muted); }
  .pick-hint { margin-top: 6px; font-size: 11px; color: var(--text-muted); }

  .file-names {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 8px;
    justify-content: center;
  }

  .err-msg {
    background: #450a0a;
    border: 1px solid var(--danger);
    color: #fca5a5;
    padding: 8px 12px;
    border-radius: var(--radius);
    font-size: 12px;
  }

  /* Success state */
  .success {
    padding: 24px 20px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    text-align: center;
  }
  .success-icon { font-size: 36px; }
  .success-id { font-size: 18px; font-weight: 700; color: var(--accent); }
  .success-files { display: flex; flex-wrap: wrap; gap: 4px; justify-content: center; }

  .type-counts {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: center;
  }
  .type-chip {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
  }
  .text-chip  { background: #1e3a5f; color: #93c5fd; }
  .audio-chip { background: #3b2000; color: #fbbf24; }
  .image-chip { background: #052e16; color: #86efac; }
  .video-chip { background: #2e1065; color: #c4b5fd; }

  .pipeline-list {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    width: 100%;
    max-width: 360px;
    text-align: left;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .pipeline-title {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 2px;
  }
  .pipeline-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--text-2);
  }
  .pipeline-dot { font-size: 10px; }
  .pipeline-dot.running { color: #76b900; }
  .pipeline-dot.pending { color: #f59e0b; }

  :global(.badge.amber) { background: #3b2000; color: #fbbf24; }
  :global(.badge.green) { background: #052e16; color: #86efac; }
  :global(.badge.purple) { background: #2e1065; color: #c4b5fd; }
</style>
