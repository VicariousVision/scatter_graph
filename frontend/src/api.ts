import type {
  ChatMessage,
  Conversation,
  ConversationSummary,
  DocumentInfo,
  GraphMeta,
  GraphResponse,
  Health,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new Error('Cannot reach the API server. Is the backend running?')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // keep the status text
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request<Health>('/health'),

  documents: () => request<DocumentInfo[]>('/documents'),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentInfo>('/documents', { method: 'POST', body: form })
  },

  graph: (opts: { documentId?: string; types?: string[]; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts.documentId) params.set('document_id', opts.documentId)
    if (opts.types?.length) params.set('types', opts.types.join(','))
    params.set('limit', String(opts.limit ?? 500))
    return request<GraphResponse>(`/graph?${params}`)
  },
  graphMeta: () => request<GraphMeta>('/graph/meta'),

  conversations: () => request<ConversationSummary[]>('/conversations'),
  createConversation: () => request<Conversation>('/conversations', json({})),
  conversation: (id: string) => request<Conversation>(`/conversations/${encodeURIComponent(id)}`),
  sendMessage: (id: string, content: string) =>
    request<ChatMessage>(`/conversations/${encodeURIComponent(id)}/messages`, json({ content })),
}
