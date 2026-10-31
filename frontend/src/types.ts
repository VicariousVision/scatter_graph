export interface ComponentStatus {
  ok: boolean
  detail: string
}

export interface Health {
  ok: boolean
  components: Record<string, ComponentStatus>
  models: { llm: string; embedder: string }
  ingestion: {
    queued: number
    processing: number
    current: { file_name: string; stage: string } | null
  }
}

export type DocumentStatus = 'queued' | 'processing' | 'done' | 'failed'

export interface DocumentInfo {
  id: string
  file_name: string
  file_size: number
  uploaded_at: string | null
  status: DocumentStatus
  stage: string | null
  error: string | null
  chunks: number
  entities: number
}

export interface GraphNode {
  id: string
  name: string
  label: string
  properties: Record<string, unknown>
  degree?: number
  documents?: string[]
}

export interface GraphLink {
  id: string
  type: string
  source: string
  target: string
  properties: Record<string, unknown>
}

export interface GraphPayload {
  nodes: GraphNode[]
  links: GraphLink[]
}

export interface GraphResponse extends GraphPayload {
  total_nodes: number
  truncated: boolean
}

export interface GraphMeta {
  entity_types: { label: string; count: number }[]
  documents: { id: string; file_name: string; entities: number }[]
}

export interface Source {
  document_id: string | null
  file_name: string
  chunk_index: number | null
  score: number
  snippet: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string | null
  sources: Source[]
  graph: GraphPayload | null
  pending?: boolean
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string | null
  updated_at: string | null
}

export interface Conversation {
  id: string
  title: string
  messages: ChatMessage[]
}

/** The subgraph behind one answer, shown in the graph view. */
export interface AnswerContext {
  messageId: string
  question: string
  graph: GraphPayload
}
