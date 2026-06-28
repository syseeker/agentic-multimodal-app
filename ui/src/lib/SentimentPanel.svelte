<script>
  import { onMount } from 'svelte'
  import { sentimentData } from '../stores.js'

  export let caseId

  let loading = false
  let error = null

  onMount(async () => {
    if (!$sentimentData) {
      loading = true
      try {
        const r = await fetch(`/api/cases/${caseId}/sentiment`)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        sentimentData.set(await r.json())
      } catch (e) {
        error = e.message
      } finally {
        loading = false
      }
    }
  })

  // Heuristically extract paralinguistic signals from analysis text
  function extractSignals(text) {
    if (!text) return []
    const signals = []

    const stressMatch = text.match(/stress[:\s]+([a-z]+)/i)
    if (stressMatch) signals.push({ label: 'Stress', value: stressMatch[1] })

    const paceMatch = text.match(/(?:speech rate|pace|speed)[:\s]+([a-z]+)/i)
    if (paceMatch) signals.push({ label: 'Pace', value: paceMatch[1] })

    const toneMatch = text.match(/tone[:\s]+([a-z]+)/i)
    if (toneMatch) signals.push({ label: 'Tone', value: toneMatch[1] })

    const confidenceMatch = text.match(/confidence[:\s]+([a-z]+)/i)
    if (confidenceMatch) signals.push({ label: 'Confidence', value: confidenceMatch[1] })

    const deceptionMatch = text.match(/deception[:\s]+([a-z]+)/i)
    if (deceptionMatch) signals.push({ label: 'Deception', value: deceptionMatch[1] })

    return signals
  }
</script>

<div class="sentiment-panel">
  <div class="panel-header">
    <div class="panel-title">Paralinguistic Analysis</div>
    <div class="panel-sub">MERaLiON audio analysis per statement</div>
  </div>

  {#if loading}
    <div class="state">Loading analysis data...</div>
  {:else if error}
    <div class="state err">Error: {error}</div>
  {:else if !$sentimentData || !$sentimentData.available}
    <div class="empty">
      <div class="empty-icon">🎙️</div>
      <div class="empty-title">No audio analysis available</div>
      <div class="empty-sub">
        Audio files for this case have not been processed yet, or no speech was detected.
        Audio analysis is produced by the Parakeet ASR + MERaLiON pipeline (Phase 4).
      </div>
      <div class="pipeline-note">
        To process audio:
        <code>python3 data/audio/process_audio.py --case {caseId}</code>
      </div>
    </div>
  {:else}
    <div class="entries">
      {#each $sentimentData.entries as entry}
        <div class="entry-card">
          <div class="entry-header">
            <span class="entry-icon">🎙️</span>
            <span class="entry-source">{entry.source}</span>
          </div>

          {#if entry.analysis && entry.analysis !== '[No speech detected]'}
            {@const signals = extractSignals(entry.analysis)}
            {#if signals.length > 0}
              <div class="signals">
                {#each signals as sig}
                  <div class="signal-chip">
                    <span class="sig-label">{sig.label}</span>
                    <span class="sig-value">{sig.value}</span>
                  </div>
                {/each}
              </div>
            {/if}
            <pre class="entry-text">{entry.analysis}</pre>
          {:else}
            <div class="no-speech muted">No speech detected in this audio file.</div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .sentiment-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  .panel-header {
    padding: 14px 20px 10px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
  }
  .panel-title { font-size: 15px; font-weight: 600; }
  .panel-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

  .state { padding: 20px; color: var(--text-muted); }
  .state.err { color: var(--danger); }

  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 40px;
    text-align: center;
  }
  .empty-icon { font-size: 48px; opacity: 0.4; }
  .empty-title { font-size: 16px; font-weight: 600; color: var(--text-2); }
  .empty-sub { font-size: 13px; color: var(--text-muted); max-width: 400px; line-height: 1.6; }
  .pipeline-note {
    margin-top: 8px;
    font-size: 12px;
    color: var(--text-muted);
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 8px 14px;
    border-radius: var(--radius);
  }
  .pipeline-note code {
    display: block;
    margin-top: 4px;
    font-family: var(--font-mono);
    color: var(--accent);
  }

  .entries {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .entry-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }

  .entry-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--surface-2);
    font-weight: 600;
    font-size: 13px;
  }
  .entry-icon { font-size: 16px; }
  .entry-source { color: var(--text); }

  .signals {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }
  .signal-chip {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 99px;
    padding: 3px 10px;
    font-size: 11px;
  }
  .sig-label { color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.3px; }
  .sig-value { color: var(--text); font-weight: 600; text-transform: capitalize; }

  .entry-text {
    padding: 12px 14px;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text-2);
  }

  .no-speech {
    padding: 12px 14px;
    font-size: 12px;
    font-style: italic;
  }
</style>
