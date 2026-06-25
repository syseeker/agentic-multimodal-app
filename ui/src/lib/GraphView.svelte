<script>
  import { onMount } from 'svelte';
  import cytoscape from 'cytoscape';

  export let graph = { nodes: [], edges: [] };
  export let keyPlayers = [];

  let el;
  let cy;

  const TYPE_COLOR = {
    person: '#76b900', organization: '#3a86ff', location: '#ff9f1c',
    phone: '#8338ec', account: '#ef476f', money: '#06d6a0',
    item: '#118ab2', event: '#ffd166', other: '#9aa0a6'
  };

  function render() {
    if (!el) return;
    const keyIds = new Set(keyPlayers.map((k) => k.id));
    const elements = [
      ...graph.nodes.map((n) => ({
        data: { id: n.id, label: n.name || n.id, type: n.type },
        classes: keyIds.has(n.id) ? 'key' : ''
      })),
      ...graph.edges.map((e) => ({
        data: { source: e.source, target: e.target, label: e.relation }
      }))
    ];
    if (cy) cy.destroy();
    cy = cytoscape({
      container: el,
      elements,
      style: [
        { selector: 'node', style: {
          'background-color': (n) => TYPE_COLOR[n.data('type')] || '#9aa0a6',
          label: 'data(label)', color: '#e8eaed', 'font-size': 10,
          'text-valign': 'center', 'text-halign': 'center', width: 26, height: 26
        }},
        { selector: 'node.key', style: { width: 44, height: 44, 'border-width': 3, 'border-color': '#fff' }},
        { selector: 'edge', style: {
          width: 1.5, 'line-color': '#5f6368', 'target-arrow-color': '#5f6368',
          'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
          label: 'data(label)', 'font-size': 8, color: '#9aa0a6'
        }}
      ],
      layout: { name: 'cose', animate: false, padding: 20 }
    });
  }

  onMount(render);
  $: if (cy !== undefined || el) render();
</script>

<div class="graph" bind:this={el}></div>

<style>
  .graph { width: 100%; height: 420px; background: #16181d; border-radius: 8px; }
</style>
