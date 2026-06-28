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
          <div class="success-msg">{result.message}</div>
          <div class="success-files">
            {#each result.files_saved as f}
              <span class="badge blue">{f}</span>
            {/each}
          </div>
          <button class="btn primary" on:click={close} style="margin-top:12px">Done</button>
        </div>
      {:else}
        <div class="modal-body">
          <!-- File picker: supports folder upload via webkitdirectory -->
          <div class="field">
            <label>Evidence files</label>
            <div class="file-zone" class:has-files={files.length > 0}>
              <input
                type="file"
                multiple
                webkitdirectory
                on:change={onFileChange}
                style="display:none"
                id="file-input"
              />
              <label for="file-input" class="file-label">
                {#if files.length === 0}
                  Click to select files or an entire case folder
                {:else}
                  {files.length} file{files.length !== 1 ? 's' : ''} selected:
                  <div class="file-names">
                    {#each files.slice(0, 6) as f}
                      <span class="badge blue">{f.name}</span>
                    {/each}
                    {#if files.length > 6}
                      <span class="muted">+{files.length - 6} more</span>
                    {/if}
                  </div>
                {/if}
              </label>
            </div>
            <div class="hint">Or select individual files without webkitdirectory by right-clicking the button</div>
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
    padding: 16px;
    cursor: pointer;
    font-size: 13px;
    color: var(--text-2);
    text-align: center;
  }

  .file-names {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 8px;
    justify-content: center;
  }

  .hint { font-size: 11px; color: var(--text-muted); }

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
    padding: 30px 20px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    text-align: center;
  }
  .success-icon { font-size: 36px; }
  .success-id { font-size: 18px; font-weight: 700; color: var(--accent); }
  .success-msg { font-size: 13px; color: var(--text-2); max-width: 340px; }
  .success-files { display: flex; flex-wrap: wrap; gap: 4px; justify-content: center; }
</style>
