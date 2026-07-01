<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { marked } from 'marked'
  import { chatHistory, pendingPlan, streamingActive } from '../stores.js'

  export let caseId
  export let caseMeta = {}

  let input = ''
  let streaming = false
  let thinkingStep = ''
  let elapsed = 0
  let elapsedTimer = null
  let msgContainer
  let textareaEl
  let greetedCase = null  // tracks which caseId has already been greeted

  // Map AI-Q intermediate_data name field to human-readable step labels
  function stepLabel(name) {
    if (!name) return ''
    if (name.includes('intent_classifier')) return 'Classifying intent…'
    if (name.includes('shallow_researcher') || name.includes('researcher')) return 'Searching knowledge base…'
    if (name.includes('report_writer') || name.includes('writer')) return 'Writing report…'
    if (name.includes('workflow')) return 'Running investigation pipeline…'
    if (/nvidia\//i.test(name)) return 'Generating response…'
    if (name.startsWith('Function Start:')) {
      const step = name.replace('Function Start:', '').trim()
      return `Running ${step}…`
    }
    return ''
  }

  function startThinkingTimer() {
    elapsed = 0
    clearInterval(elapsedTimer)
    elapsedTimer = setInterval(() => { elapsed += 1 }, 1000)
  }

  function stopThinkingTimer() {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }

  onDestroy(stopThinkingTimer)

  // Detect a plan in an assistant message:
  // A plan is a numbered list with >= 3 steps, or contains "Investigation Plan" heading
  function detectPlan(text) {
    const hasHeading = /investigation plan|forensic plan|proposed plan/i.test(text)
    const numberedLines = (text.match(/^\s*\d+\.\s+.+/gm) || []).length
    return hasHeading || numberedLines >= 3
  }

  async function scrollBottom() {
    await tick()
    if (msgContainer) msgContainer.scrollTop = msgContainer.scrollHeight
  }

  // Case context prefix prepended to every outgoing user message.
  // This is more reliable than a system message since AI-Q's NAT
  // replaces the system role with its own Jinja2 template.
  function casePrefix() {
    return `[Case: ${caseId} | Type: ${caseMeta.case_type ?? 'unknown'} | District: ${caseMeta.district ?? 'unknown'} | Suspect: ${caseMeta.suspect_name ?? 'unknown'}]\n\n`
  }

  async function sendMessage(content, opts = {}) {
    // opts.hidden = true → message not shown in UI (used for auto-init)
    if (!content.trim() || streaming) return

    if (!opts.hidden) {
      const userMsg = { role: 'user', content: content.trim(), ts: new Date() }
      chatHistory.update(h => [...h, userMsg])
    }
    input = ''
    pendingPlan.set(null)
    await scrollBottom()

    let history
    chatHistory.subscribe(h => { history = h })()

    // Prepend case context to this message (user turn — AI-Q always reads it)
    const fullContent = opts.prefixed ? content : casePrefix() + content

    const messages = [
      ...history
        .filter(m => !opts.hidden || m.role !== 'user' || m.content !== content)
        .map(m => ({ role: m.role, content: m.content })),
      // If hidden, the message wasn't added to history — add it now for API only
      ...(opts.hidden ? [{ role: 'user', content: fullContent }] : []),
    ]

    // For non-hidden messages, replace the last user entry with the prefixed version
    if (!opts.hidden && messages.length > 0) {
      const lastUserIdx = messages.map(m => m.role).lastIndexOf('user')
      if (lastUserIdx !== -1) messages[lastUserIdx].content = fullContent
    }

    // Add placeholder for assistant response
    const assistantMsg = { role: 'assistant', content: '', ts: new Date(), streaming: true }
    chatHistory.update(h => [...h, assistantMsg])
    const assistantIdx = history.length // index in chatHistory

    streaming = true
    thinkingStep = ''
    streamingActive.set(true)
    startThinkingTimer()

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages, stream: true }),
      })

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // keep incomplete line

        for (const line of lines) {
          // Parse AI-Q agent step events for live status display
          if (line.startsWith('intermediate_data: ')) {
            try {
              const d = JSON.parse(line.slice('intermediate_data: '.length).trim())
              const label = stepLabel(d.name ?? '')
              if (label) thinkingStep = label
            } catch { /* ignore */ }
            continue
          }

          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') break

          try {
            const parsed = JSON.parse(data)
            // Server-side proxy error (e.g. AI-Q timeout)
            if (parsed?.error) {
              throw new Error(parsed.error)
            }
            // OpenAI SSE format
            const delta = parsed?.choices?.[0]?.delta?.content ?? ''
            // Fallback: plain content field
            const plain = parsed?.content ?? parsed?.text ?? ''
            const chunk = delta || plain

            if (chunk) {
              accumulated += chunk
              chatHistory.update(h => {
                const updated = [...h]
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: accumulated,
                }
                return updated
              })
              await scrollBottom()
            }
          } catch (parseErr) {
            if (parseErr.message && !parseErr.message.startsWith('JSON')) throw parseErr
            // malformed JSON chunk — ignore
          }
        }
      }

      // Mark streaming done; if no content arrived, show a diagnostic hint
      chatHistory.update(h => {
        const updated = [...h]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: accumulated || '_No response received. Sherlock may still be processing — try again in a moment._',
          streaming: false,
        }
        return updated
      })

      // Check if the response looks like a plan awaiting approval
      if (detectPlan(accumulated)) {
        pendingPlan.set(accumulated)
      }
    } catch (err) {
      chatHistory.update(h => {
        const updated = [...h]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `[Connection error: ${err.message}]`,
          error: true,
          streaming: false,
        }
        return updated
      })
    } finally {
      streaming = false
      streamingActive.set(false)
      stopThinkingTimer()
      await scrollBottom()
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  function approvePlan() {
    pendingPlan.set(null)
    sendMessage('Approved. Please proceed with the investigation plan.')
  }

  function rejectPlan() {
    pendingPlan.set(null)
    const reason = prompt('Reason for rejection (optional):') ?? ''
    const msg = reason ? `Rejected. Please revise the plan: ${reason}` : 'Rejected. Please revise the investigation plan.'
    sendMessage(msg)
  }

  // Configure marked for GitHub Flavored Markdown (tables, strikethrough, etc.)
  marked.setOptions({ gfm: true, breaks: true })

  function renderMessage(text) {
    if (!text) return ''
    return marked.parse(text)
  }

  // Clear history and greet whenever the user switches to a different case.
  $: if (caseId && caseId !== greetedCase) {
    greetedCase = caseId
    chatHistory.set([])
    pendingPlan.set(null)
    const officer = caseMeta.assigned_officer
    const greeting = `Hello${officer ? `, **${officer}**` : ''}. I'm ready to assist with case **${caseId}**. What would you like to investigate?`
    chatHistory.update(h => [...h, { role: 'assistant', content: greeting, ts: new Date(), streaming: false }])
    tick().then(scrollBottom)
  }

  onMount(() => { textareaEl?.focus() })
</script>

<div class="chat-panel">
  <!-- HITL approval banner -->
  {#if $pendingPlan}
    <div class="hitl-banner">
      <div class="hitl-text">
        <strong>Sherlock has proposed an investigation plan</strong> — review and approve before proceeding.
      </div>
      <div class="hitl-actions">
        <button class="btn primary" on:click={approvePlan}>Approve &amp; Proceed</button>
        <button class="btn danger" on:click={rejectPlan}>Reject &amp; Revise</button>
      </div>
    </div>
  {/if}

  <!-- Messages -->
  <div class="messages" bind:this={msgContainer}>
    {#if !$chatHistory.some(m => m.role === 'user')}
      <div class="welcome">
        <div class="suggestions" class:disabled={streaming}>
          {#each [
            `Who are the suspects in case ${caseId}?`,
            'Summarize the key evidence.',
            'Build an investigation plan for this case.',
            'What are the relationships between key parties?',
          ] as s}
            <button class="suggestion" disabled={streaming} on:click={() => sendMessage(s)}>{s}</button>
          {/each}
        </div>
      </div>
    {/if}

    {#each $chatHistory as msg}
      <div class="message {msg.role}" class:error={msg.error}>
        <div class="msg-role">
          {msg.role === 'user' ? 'Investigator' : 'Sherlock'}
          <span class="msg-ts">{msg.ts?.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) ?? ''}</span>
          {#if msg.streaming}
            <span class="typing-dot"></span>
          {/if}
        </div>
        <div class="msg-body">
          {#if msg.streaming && !msg.content}
            <div class="thinking-state">
              <span class="spinner sm"></span>
              <span class="thinking-text">{thinkingStep || 'Sherlock is analyzing…'}</span>
              <span class="elapsed-badge">{elapsed}s</span>
            </div>
          {:else}
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html renderMessage(msg.content)}
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <!-- Input -->
  <div class="input-row">
    <textarea
      bind:this={textareaEl}
      bind:value={input}
      on:keydown={handleKey}
      placeholder="Ask Sherlock… (Enter to send, Shift+Enter for newline)"
      rows="2"
      disabled={streaming}
    ></textarea>
    <button class="btn primary send-btn" on:click={() => sendMessage(input)} disabled={streaming || !input.trim()}>
      {streaming ? '...' : 'Send'}
    </button>
  </div>
</div>

<style>
  .chat-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  /* HITL banner */
  .hitl-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 12px 20px;
    background: #1a2a00;
    border-bottom: 1px solid var(--accent-dim);
    flex-shrink: 0;
  }
  .hitl-text { font-size: 13px; color: #c8e880; }
  .hitl-actions { display: flex; gap: 8px; }

  /* Messages */
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .welcome {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: auto;
    max-width: 540px;
    text-align: center;
    padding: 40px 0;
  }
  .welcome-title { font-size: 18px; font-weight: 600; color: var(--text); }
  .welcome-sub { font-size: 13px; color: var(--text-2); line-height: 1.6; }

  .init-status {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-muted);
    justify-content: center;
  }

  .suggestions { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
  .suggestions.disabled { opacity: 0.4; pointer-events: none; }
  .suggestion {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-2);
    padding: 8px 14px;
    font-size: 13px;
    cursor: pointer;
    text-align: left;
    transition: background 0.15s, color 0.15s;
  }
  .suggestion:hover { background: var(--surface-2); color: var(--text); }

  .message {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 800px;
  }
  .message.assistant { align-self: flex-start; }
  .message.user { align-self: flex-end; }

  .msg-role {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .message.user .msg-role { color: var(--accent); justify-content: flex-end; }
  .message.assistant .msg-role { color: var(--info); }
  .msg-ts { font-weight: 400; text-transform: none; letter-spacing: 0; }

  .typing-dot {
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--text-muted);
    animation: pulse 1s infinite;
  }
  @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }

  .thinking-state {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-muted);
    font-size: 13px;
    font-style: italic;
    padding: 4px 0;
  }
  .thinking-text { animation: pulse 1.5s ease-in-out infinite; }
  .elapsed-badge {
    font-style: normal;
    font-size: 11px;
    color: var(--text-muted);
    background: var(--surface-2);
    padding: 1px 6px;
    border-radius: 10px;
    opacity: 0.7;
  }

  .msg-body {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    line-height: 1.65;
    font-size: 13.5px;
    word-break: break-word;
    overflow-x: auto;
  }
  .message.user .msg-body {
    background: #0d1f00;
    border-color: var(--accent-dim);
    color: #d4f08a;
  }
  .message.error .msg-body { border-color: var(--danger); color: #fca5a5; }

  /* ── Markdown rendering inside message bubbles ── */
  :global(.msg-body p) { margin: 0 0 8px; line-height: 1.65; }
  :global(.msg-body p:last-child) { margin-bottom: 0; }

  :global(.msg-body h1, .msg-body h2, .msg-body h3, .msg-body h4) {
    color: var(--accent);
    font-weight: 700;
    margin: 12px 0 6px;
    line-height: 1.3;
  }
  :global(.msg-body h1) { font-size: 16px; }
  :global(.msg-body h2) { font-size: 15px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
  :global(.msg-body h3) { font-size: 13.5px; color: var(--text); }
  :global(.msg-body h4) { font-size: 13px; color: var(--text-2); }

  :global(.msg-body strong) { font-weight: 700; color: var(--text); }
  :global(.msg-body em) { font-style: italic; color: var(--text-2); }

  :global(.msg-body code) {
    background: var(--surface-2);
    padding: 1px 5px;
    border-radius: 3px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: #c8e880;
  }
  :global(.msg-body pre) {
    background: #0a0c10;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 14px;
    overflow-x: auto;
    margin: 8px 0;
  }
  :global(.msg-body pre code) {
    background: none;
    padding: 0;
    color: #c8e880;
    font-size: 12px;
  }

  :global(.msg-body ul, .msg-body ol) {
    margin: 6px 0 8px 20px;
    padding: 0;
  }
  :global(.msg-body li) { margin-bottom: 3px; line-height: 1.6; }
  :global(.msg-body li > p) { margin: 0; }

  :global(.msg-body hr) {
    border: none;
    border-top: 1px solid var(--border);
    margin: 12px 0;
  }

  :global(.msg-body blockquote) {
    border-left: 3px solid var(--accent-dim);
    margin: 8px 0;
    padding: 4px 12px;
    color: var(--text-2);
    font-style: italic;
  }

  /* Tables */
  :global(.msg-body table) {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
    font-size: 12.5px;
    overflow-x: auto;
    display: block;
  }
  :global(.msg-body th) {
    background: var(--surface-2);
    color: var(--text);
    font-weight: 600;
    text-align: left;
    padding: 7px 10px;
    border: 1px solid var(--border);
    white-space: nowrap;
  }
  :global(.msg-body td) {
    padding: 6px 10px;
    border: 1px solid var(--border);
    vertical-align: top;
    line-height: 1.5;
  }
  :global(.msg-body tr:nth-child(even) td) { background: rgba(255,255,255,0.02); }
  :global(.msg-body tr:hover td) { background: rgba(118,185,0,0.05); }

  /* Input */
  .input-row {
    display: flex;
    gap: 10px;
    padding: 14px 20px;
    border-top: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
    align-items: flex-end;
  }
  .input-row textarea {
    resize: none;
    flex: 1;
    font-size: 13px;
    line-height: 1.5;
  }
  .send-btn { height: 56px; min-width: 64px; }
</style>
