import { writable } from 'svelte/store'

// Currently selected case (full metadata object or null)
export const selectedCase = writable(null)

// Chat history: [{role: 'user'|'assistant', content: string, ts: Date}]
export const chatHistory = writable([])

// Active right-panel tab: 'chat' | 'graph' | 'evidence' | 'sentiment'
export const activeTab = writable('chat')

// HITL: when truthy, contains the plan text waiting for approval
export const pendingPlan = writable(null)

// Graph elements loaded for the current case
export const graphElements = writable([])

// Evidence file list for current case
export const evidenceFiles = writable([])

// Currently open evidence file content
export const openEvidence = writable(null)

// Sentiment data for current case
export const sentimentData = writable(null)

// Backend health status
export const health = writable({ aiq: null, neo4j: null })

// True while ChatPanel is waiting for an AI-Q response — used to warn before case switch
export const streamingActive = writable(false)
