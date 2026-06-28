<script>
  import { onMount, createEventDispatcher } from 'svelte'
  import { selectedCase } from '../stores.js'
  import CaseUpload from './CaseUpload.svelte'

  const dispatch = createEventDispatcher()

  let cases = []
  let filter = ''
  let loading = true
  let error = null

  async function loadCases() {
    loading = true
    error = null
    try {
      const r = await fetch('/api/cases')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      cases = await r.json()
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  }

  onMount(loadCases)

  async function onUploaded(e) {
    await loadCases()
    // Auto-select the newly created case
    const newCase = cases.find(c => c.case_id === e.detail.case_id)
    if (newCase) dispatch('select', newCase)
  }

  $: filtered = cases.filter(c =>
    !filter || c.case_id.toLowerCase().includes(filter.toLowerCase()) ||
    (c.case_type ?? '').toLowerCase().includes(filter.toLowerCase()) ||
    (c.district ?? '').toLowerCase().includes(filter.toLowerCase())
  )

  const TYPE_COLORS = {
    homicide: 'red',
    fraud: 'amber',
    robbery: 'amber',
    trafficking: 'red',
    cybercrime: 'blue',
    assault: 'amber',
  }

  function colorFor(type) {
    return TYPE_COLORS[type?.toLowerCase()] ?? 'blue'
  }
</script>

<div class="selector">
  <div class="search-row">
    <input type="text" bind:value={filter} placeholder="Filter cases..." />
  </div>

  {#if loading}
    <div class="state">Loading cases...</div>
  {:else if error}
    <div class="state err">Error: {error}</div>
  {:else if filtered.length === 0}
    <div class="state">No cases match</div>
  {:else}
    <div class="count muted">{filtered.length} case{filtered.length !== 1 ? 's' : ''}</div>
    <ul class="list">
      {#each filtered as c}
        {@const active = $selectedCase?.case_id === c.case_id}
        <li>
          <button
            class="case-item"
            class:active
            on:click={() => dispatch('select', c)}
          >
            <span class="badge {colorFor(c.case_type)} case-type">{c.case_type ?? 'unknown'}</span>
            <span class="case-id mono truncate">{c.case_id}</span>
            <span class="case-district muted truncate">{c.district ?? ''}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  <CaseUpload on:uploaded={onUploaded} />
</div>

<style>
  .selector {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }

  .list {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
  }

  .search-row {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }

  .count {
    padding: 6px 12px 2px;
    font-size: 11px;
  }

  .state {
    padding: 20px 12px;
    color: var(--text-muted);
    font-size: 13px;
  }
  .state.err { color: var(--danger); }

  .list {
    list-style: none;
    overflow-y: auto;
    flex: 1;
  }

  .case-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
    text-align: left;
    padding: 9px 12px;
    background: transparent;
    border: none;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    transition: background 0.1s;
  }
  .case-item:hover { background: var(--surface-2); }
  .case-item.active { background: var(--surface-2); border-left: 3px solid var(--accent); }

  .case-type { font-size: 10px; align-self: flex-start; text-transform: capitalize; }
  .case-id { font-size: 11px; color: var(--text); }
  .case-district { font-size: 11px; }
</style>
