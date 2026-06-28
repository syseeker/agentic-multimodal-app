<script>
  import { onMount, onDestroy, afterUpdate } from 'svelte'
  import cytoscape from 'cytoscape'
  import { graphElements } from '../stores.js'

  export let caseId

  let container
  let cy = null
  let loading = false
  let error = null
  let stats = { nodes: 0, edges: 0 }

  const NODE_STYLES = [
    { selector: 'node', style: {
      'label': 'data(label)',
      'background-color': 'data(color)',
      'color': '#e2e8f0',
      'font-size': '11px',
      'text-valign': 'bottom',
      'text-margin-y': '4px',
      'text-outline-color': '#0f1117',
      'text-outline-width': '2px',
      'width': '36px',
      'height': '36px',
      'border-width': '2px',
      'border-color': '#2a2d3a',
      'transition-property': 'border-color, width, height',
      'transition-duration': '0.15s',
    }},
    { selector: 'node:selected', style: {
      'border-color': '#76b900',
      'border-width': '3px',
      'width': '44px',
      'height': '44px',
    }},
    { selector: 'edge', style: {
      'curve-style': 'bezier',
      'width': 1.5,
      'line-color': '#2a2d3a',
      'target-arrow-color': '#2a2d3a',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.8,
      'label': 'data(label)',
      'font-size': '9px',
      'color': '#64748b',
      'text-background-color': '#0f1117',
      'text-background-opacity': 1,
      'text-background-padding': '2px',
    }},
    { selector: 'edge:selected', style: {
      'line-color': '#76b900',
      'target-arrow-color': '#76b900',
    }},
  ]

  function buildGraph(elements) {
    if (!container) return
    if (cy) { cy.destroy(); cy = null }

    cy = cytoscape({
      container,
      elements,
      style: NODE_STYLES,
      layout: {
        name: 'cose',
        animate: false,
        randomize: true,
        nodeDimensionsIncludeLabels: true,
        idealEdgeLength: 100,
        nodeRepulsion: 400000,
        gravity: 0.25,
        numIter: 1000,
      },
      wheelSensitivity: 0.3,
    })

    cy.on('tap', 'node', e => {
      selectedNode = e.target.data()
    })
    cy.on('tap', e => {
      if (e.target === cy) selectedNode = null
    })

    stats = { nodes: cy.nodes().length, edges: cy.edges().length }
  }

  let selectedNode = null

  // Re-build whenever elements change and container is ready
  $: if (container && $graphElements.length > 0) {
    buildGraph($graphElements)
  }

  onMount(async () => {
    if ($graphElements.length === 0) {
      loading = true
      try {
        const r = await fetch(`/api/cases/${caseId}/graph`)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const d = await r.json()
        graphElements.set(d.elements || [])
        stats = { nodes: d.node_count ?? 0, edges: d.edge_count ?? 0 }
      } catch (e) {
        error = e.message
      } finally {
        loading = false
      }
    } else if (container) {
      buildGraph($graphElements)
    }
  })

  onDestroy(() => { if (cy) cy.destroy() })

  function fitGraph() { cy?.fit(undefined, 40) }
  function resetLayout() { cy?.layout({ name: 'cose', animate: true, randomize: true, idealEdgeLength: 100, nodeRepulsion: 400000, gravity: 0.25 }).run() }

  const LEGEND = [
    { label: 'Person', color: '#3b82f6' },
    { label: 'Organization', color: '#f59e0b' },
    { label: 'Location', color: '#22c55e' },
    { label: 'Evidence', color: '#ef4444' },
    { label: 'Other', color: '#64748b' },
  ]
</script>

<div class="graph-panel">
  <!-- Toolbar -->
  <div class="toolbar">
    <div class="stats muted">
      {stats.nodes} nodes &middot; {stats.edges} edges
    </div>
    <div class="legend">
      {#each LEGEND as l}
        <span class="legend-item">
          <span class="legend-dot" style="background:{l.color}"></span>
          {l.label}
        </span>
      {/each}
    </div>
    <div style="margin-left:auto; display:flex; gap:6px;">
      <button class="btn ghost" on:click={fitGraph}>Fit</button>
      <button class="btn ghost" on:click={resetLayout}>Re-layout</button>
    </div>
  </div>

  <div class="graph-body">
    <!-- Cytoscape canvas -->
    <div class="cy-container" bind:this={container}>
      {#if loading}
        <div class="overlay">Loading graph...</div>
      {:else if error}
        <div class="overlay err">Error: {error}</div>
      {:else if $graphElements.length === 0}
        <div class="overlay muted">No graph data for this case.</div>
      {/if}
    </div>

    <!-- Node detail panel -->
    {#if selectedNode}
      <div class="node-detail">
        <div class="nd-header">
          <span class="badge blue">{selectedNode.type}</span>
          <strong>{selectedNode.label}</strong>
          <button class="btn ghost" style="margin-left:auto; padding:2px 8px;" on:click={() => selectedNode = null}>✕</button>
        </div>
        <div class="nd-props">
          {#each Object.entries(selectedNode).filter(([k]) => !['id','label','type','color'].includes(k)) as [k, v]}
            <div class="prop-row">
              <span class="prop-key">{k}</span>
              <span class="prop-val">{v ?? '—'}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .graph-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  .toolbar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
    flex-wrap: wrap;
  }
  .stats { font-size: 12px; }
  .legend {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: var(--text-2);
  }
  .legend-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .graph-body {
    flex: 1;
    display: flex;
    overflow: hidden;
    position: relative;
  }

  .cy-container {
    flex: 1;
    background: var(--bg);
    position: relative;
  }

  .overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    color: var(--text-muted);
    background: var(--bg);
  }
  .overlay.err { color: var(--danger); }

  /* Node detail */
  .node-detail {
    width: 260px;
    flex-shrink: 0;
    border-left: 1px solid var(--border);
    background: var(--surface);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .nd-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .nd-header strong { font-size: 13px; }
  .nd-props { overflow-y: auto; flex: 1; padding: 8px 0; }
  .prop-row {
    display: grid;
    grid-template-columns: 100px 1fr;
    gap: 8px;
    padding: 5px 12px;
    font-size: 12px;
    border-bottom: 1px solid var(--border);
  }
  .prop-key { color: var(--text-muted); }
  .prop-val { color: var(--text); word-break: break-word; }
</style>
