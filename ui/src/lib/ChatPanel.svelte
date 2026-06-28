<script>
  import { onMount, tick } from 'svelte'
  import { chatHistory, pendingPlan } from '../stores.js'

  export let caseId
  export let caseMeta = {}

  let input = ''
  let streaming = false
  let msgContainer
  let textareaEl

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

  async function sendMessage(content) {
    if (!content.trim() || streaming) return

    const userMsg = { role: 'user', content: content.trim(), ts: new Date() }
    chatHistory.update(h => [...h, userMsg])
    input = ''
    pendingPlan.set(null)
    await scrollBottom()

    // Build messages list for AI-Q — inject case context as first system turn
    let history
    chatHistory.subscribe(h => { history = h })()
    const caseContext = `You are Sherlock, a forensic investigation co-worker for the Singapore Police Force. Current case: ${caseId}. Case type: ${caseMeta.case_type ?? 'unknown'}. District: ${caseMeta.district ?? 'unknown'}. Suspect: ${caseMeta.suspect_name ?? 'unknown'}. When querying the graph or knowledge base, always filter by case_id = "${caseId}".`

    const messages = [
      { role: 'system', content: caseContext },
      ...history.map(m => ({ role: m.role, content: m.content })),
    ]

    // Add placeholder for assistant response
    const assistantMsg = { role: 'assistant', content: '', ts: new Date(), streaming: true }
    chatHistory.update(h => [...h, assistantMsg])
    const assistantIdx = history.length // index in chatHistory

    streaming = true

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
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') break

          try {
            const parsed = JSON.parse(data)
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
          } catch { /* malformed chunk */ }
        }
      }

      // Mark streaming done
      chatHistory.update(h => {
        const updated = [...h]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
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

  // Markdown-light renderer: bold, inline code, numbered lists
  function renderMessage(text) {
    if (!text) return ''
    return text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      // Bold
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // Inline code
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // Headers ##
      .replace(/^## (.+)$/gm, '<strong class="h2">$1</strong>')
      // Newlines
      .replace(/\n/g, '<br>')
  }

  onMount(() => textareaEl?.focus())
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
    {#if $chatHistory.length === 0}
      <div class="welcome">
        <div class="welcome-title">Investigating {caseId}</div>
        <div class="welcome-sub">
          Ask Sherlock about suspects, evidence, relationships, or request an investigation plan.
        </div>
        <div class="suggestions">
          {#each [
            `Who are the suspects in case ${caseId}?`,
            'Summarize the key evidence.',
            'Build an investigation plan for this case.',
            'What are the relationships between key parties?',
          ] as s}
            <button class="suggestion" on:click={() => sendMessage(s)}>{s}</button>
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
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        <div class="msg-body">{@html renderMessage(msg.content)}</div>
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
  .suggestions { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
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

  .msg-body {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    line-height: 1.65;
    font-size: 13.5px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .message.user .msg-body {
    background: #0d1f00;
    border-color: var(--accent-dim);
    color: #d4f08a;
  }
  .message.error .msg-body { border-color: var(--danger); color: #fca5a5; }

  :global(.msg-body code) {
    background: var(--surface-2);
    padding: 1px 5px;
    border-radius: 3px;
    font-family: var(--font-mono);
    font-size: 12px;
  }
  :global(.msg-body strong.h2) {
    display: block;
    font-size: 14px;
    margin-top: 6px;
    color: var(--accent);
  }

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
