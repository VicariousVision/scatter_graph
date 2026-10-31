import { MessageSquare, MessageSquarePlus } from 'lucide-react'
import { timeAgo } from '../format'
import type { ConversationSummary } from '../types'

interface Props {
  conversations: ConversationSummary[] | undefined
  activeId: string | null
  creating: boolean
  onSelect: (id: string) => void
  onCreate: () => void
}

export function ConversationList({ conversations, activeId, creating, onSelect, onCreate }: Props) {
  return (
    <section className="panel conversations">
      <header className="panel-header">
        <h2>Conversations</h2>
        <button className="btn small" onClick={onCreate} disabled={creating}>
          <MessageSquarePlus size={14} /> New chat
        </button>
      </header>
      <ul className="conv-list">
        {conversations?.length === 0 && <li className="muted small">No conversations yet.</li>}
        {conversations?.map((c) => (
          <li key={c.id}>
            <button className={`conv${c.id === activeId ? ' active' : ''}`} onClick={() => onSelect(c.id)}>
              <MessageSquare size={14} />
              <span className="conv-title">{c.title}</span>
              <span className="muted small">{timeAgo(c.updated_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
