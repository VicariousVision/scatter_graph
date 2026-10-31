import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Scale } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { ChatPanel } from './components/ChatPanel'
import { ConversationList } from './components/ConversationList'
import { DocumentsPanel } from './components/DocumentsPanel'
import { type GraphMode, GraphView } from './components/GraphView'
import { StatusBar } from './components/StatusBar'
import type { AnswerContext, ChatMessage, Conversation } from './types'

const ACTIVE_KEY = 'legal-graphrag.activeConversation'
// Components that must be healthy before a question can be answered.
const CHAT_REQUIREMENTS = ['neo4j', 'indexes', 'ollama', 'llm', 'embedder']

function lastAnswer(messages: ChatMessage[]): AnswerContext | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role === 'assistant' && m.graph) {
      const question = messages.slice(0, i).reverse().find((x) => x.role === 'user')?.content ?? ''
      return { messageId: m.id, question, graph: m.graph }
    }
  }
  return null
}

export default function App() {
  const queryClient = useQueryClient()
  const [activeId, setActiveId] = useState<string | null>(() => localStorage.getItem(ACTIVE_KEY))
  const [graphMode, setGraphMode] = useState<GraphMode>('answer')
  const [answer, setAnswer] = useState<AnswerContext | null>(null)
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [pendingQuestion, setPendingQuestion] = useState<{ conversationId: string; text: string } | null>(null)
  const [chatError, setChatError] = useState<string | null>(null)
  const answerFor = useRef<string | null>(null)

  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 5000, retry: false })
  const documents = useQuery({
    queryKey: ['documents'],
    queryFn: api.documents,
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === 'queued' || d.status === 'processing') ? 3000 : 15000),
  })
  // Changes whenever a document finishes ingesting, so graph views refresh.
  const graphVersion = useMemo(
    () => (documents.data ?? []).filter((d) => d.status === 'done').map((d) => `${d.id}:${d.entities}`).join('|'),
    [documents.data],
  )
  const meta = useQuery({ queryKey: ['graph-meta', graphVersion], queryFn: api.graphMeta })
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: api.conversations })
  const conversation = useQuery({
    queryKey: ['conversation', activeId],
    queryFn: () => api.conversation(activeId!),
    enabled: !!activeId,
    retry: false,
  })

  // Remember the open conversation across reloads; forget it if it no longer exists.
  useEffect(() => {
    if (activeId) localStorage.setItem(ACTIVE_KEY, activeId)
    else localStorage.removeItem(ACTIVE_KEY)
  }, [activeId])
  useEffect(() => {
    if (conversation.error) setActiveId(null)
  }, [conversation.error])

  // Show the latest answer's subgraph when a conversation is opened.
  useEffect(() => {
    if (!conversation.data || answerFor.current === conversation.data.id) return
    answerFor.current = conversation.data.id
    setAnswer(lastAnswer(conversation.data.messages))
  }, [conversation.data])

  const openConversation = (id: string | null) => {
    setActiveId(id)
    setChatError(null)
    setAnswer(null)
    answerFor.current = null
  }

  const createConversation = useMutation({
    mutationFn: api.createConversation,
    onSuccess: (c) => {
      queryClient.setQueryData(['conversation', c.id], c)
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
      openConversation(c.id)
      answerFor.current = c.id
    },
  })

  const send = useMutation({
    mutationFn: async (question: string) => {
      let id = activeId
      if (!id) {
        const created = await api.createConversation()
        queryClient.setQueryData(['conversation', created.id], created)
        answerFor.current = created.id
        id = created.id
        setActiveId(id)
      }
      setPendingQuestion({ conversationId: id, text: question })
      const reply = await api.sendMessage(id, question)
      return { id, question, reply }
    },
    onMutate: () => setChatError(null),
    onSuccess: ({ id, question, reply }) => {
      const userMessage: ChatMessage = {
        id: `local-${Date.now()}`,
        role: 'user',
        content: question,
        created_at: new Date().toISOString(),
        sources: [],
        graph: null,
      }
      queryClient.setQueryData<Conversation>(['conversation', id], (old) => ({
        id,
        title: old?.title ?? question,
        messages: [...(old?.messages ?? []), userMessage, reply],
      }))
      queryClient.invalidateQueries({ queryKey: ['conversation', id] })
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
      if (reply.graph) {
        setAnswer({ messageId: reply.id, question, graph: reply.graph })
        setGraphMode('answer')
      }
    },
    onError: (e) => setChatError((e as Error).message),
    onSettled: () => setPendingQuestion(null),
  })

  const messages = useMemo(() => {
    const list = [...(conversation.data?.messages ?? [])]
    if (pendingQuestion && pendingQuestion.conversationId === activeId) {
      list.push({ id: 'pending', role: 'user', content: pendingQuestion.text, created_at: null, sources: [], graph: null })
    }
    return list
  }, [conversation.data, pendingQuestion, activeId])

  const showAnswer = (m: ChatMessage) => {
    if (!m.graph) return
    const index = messages.findIndex((x) => x.id === m.id)
    const question = messages.slice(0, index).reverse().find((x) => x.role === 'user')?.content ?? ''
    setAnswer({ messageId: m.id, question, graph: m.graph })
    setGraphMode('answer')
  }

  const failing = CHAT_REQUIREMENTS.map((k) => health.data?.components[k]).find((c) => c && !c.ok)
  const canAsk = !!health.data && !failing
  const hasDocuments = (documents.data ?? []).some((d) => d.status === 'done')
  const blockedReason = health.error
    ? 'The API server is not reachable.'
    : failing
      ? failing.detail
      : health.data && !hasDocuments
        ? 'No documents have been ingested yet. Upload a PDF first.'
        : null

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Scale size={20} />
          <span>Legal GraphRAG</span>
        </div>
        <StatusBar health={health.data} error={health.error} />
      </header>

      <div className="layout">
        <aside className="sidebar">
          <DocumentsPanel
            documents={documents.data}
            loading={documents.isLoading}
            selectedId={documentId}
            onSelect={(id) => {
              setDocumentId(id)
              setGraphMode('full')
            }}
          />
          <ConversationList
            conversations={conversations.data}
            activeId={activeId}
            creating={createConversation.isPending}
            onSelect={openConversation}
            onCreate={() => createConversation.mutate()}
          />
        </aside>

        <main className="main">
          <GraphView
            mode={graphMode}
            onModeChange={setGraphMode}
            answer={answer}
            meta={meta.data}
            documentId={documentId}
            onDocumentChange={setDocumentId}
            refreshKey={graphVersion}
          />
          <ChatPanel
            title={conversation.data?.title ?? null}
            messages={messages}
            loading={!!activeId && conversation.isLoading}
            sending={send.isPending}
            error={chatError}
            canAsk={canAsk}
            blockedReason={blockedReason}
            activeAnswerId={answer?.messageId ?? null}
            onSend={(q) => send.mutate(q)}
            onShowAnswer={showAnswer}
          />
        </main>
      </div>
    </div>
  )
}
