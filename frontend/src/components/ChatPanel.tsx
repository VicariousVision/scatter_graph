import { CircleAlert, FileText, LoaderCircle, Network, Scale, Send } from 'lucide-react'
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import type { ChatMessage } from '../types'

interface Props {
  title: string | null
  messages: ChatMessage[]
  loading: boolean
  sending: boolean
  error: string | null
  canAsk: boolean
  blockedReason: string | null
  activeAnswerId: string | null
  onSend: (question: string) => void
  onShowAnswer: (message: ChatMessage) => void
}

const SUGGESTIONS = [
  'Who are the parties and what are their roles?',
  'What are the key obligations of each party?',
  'How can the agreement be terminated?',
  'Which law governs the agreement and where are disputes resolved?',
]

export function ChatPanel(props: Props) {
  const { title, messages, loading, sending, error, canAsk, blockedReason, activeAnswerId, onSend, onShowAnswer } = props
  const [draft, setDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, sending])

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    const question = draft.trim()
    if (!question || sending || !canAsk) return
    onSend(question)
    setDraft('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) submit(e)
  }

  return (
    <section className="panel chat-panel">
      <header className="panel-header">
        <h2 className="chat-title">{title ?? 'New conversation'}</h2>
      </header>

      <div className="messages">
        {loading && (
          <div className="empty">
            <LoaderCircle size={22} className="spin" />
          </div>
        )}
        {!loading && messages.length === 0 && (
          <div className="welcome">
            <Scale size={28} />
            <h3>Ask about your documents</h3>
            <p className="muted">
              Answers come only from the uploaded documents and their knowledge graph. This assistant does not give legal
              advice.
            </p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" disabled={!canAsk || sending} onClick={() => onSend(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`message ${m.role}${m.id === activeAnswerId ? ' active' : ''}`}>
            {m.role === 'assistant' ? (
              <>
                <div className="bubble markdown">
                  <Markdown>{m.content}</Markdown>
                </div>
                {(m.sources.length > 0 || (m.graph?.nodes.length ?? 0) > 0) && (
                  <div className="message-footer">
                    {uniqueSources(m).map((s) => (
                      <span key={`${s.file_name}-${s.chunk_index}`} className="source" title={s.snippet}>
                        <FileText size={12} /> {s.file_name}
                        {s.chunk_index !== null && <span className="muted"> #{s.chunk_index + 1}</span>}
                      </span>
                    ))}
                    {(m.graph?.nodes.length ?? 0) > 0 && (
                      <button className="link-btn" onClick={() => onShowAnswer(m)}>
                        <Network size={12} /> {m.graph!.nodes.length} entities in graph
                      </button>
                    )}
                  </div>
                )}
              </>
            ) : (
              <div className="bubble">{m.content}</div>
            )}
          </div>
        ))}

        {sending && (
          <div className="message assistant">
            <div className="bubble thinking">
              <LoaderCircle size={14} className="spin" /> Searching the knowledge graph and writing an answer…
            </div>
          </div>
        )}
        {error && (
          <div className="notice error">
            <CircleAlert size={14} /> {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form className="composer" onSubmit={submit}>
        {blockedReason && <div className="composer-note">{blockedReason}</div>}
        <div className="composer-row">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={canAsk ? 'Ask a question about the documents…' : 'Waiting for the system…'}
            rows={2}
            maxLength={4000}
            disabled={!canAsk}
          />
          <button className="btn primary" type="submit" disabled={!draft.trim() || sending || !canAsk} aria-label="Send">
            {sending ? <LoaderCircle size={16} className="spin" /> : <Send size={16} />}
          </button>
        </div>
      </form>
    </section>
  )
}

function uniqueSources(m: ChatMessage) {
  const seen = new Set<string>()
  return m.sources.filter((s) => {
    const key = `${s.file_name}-${s.chunk_index}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
