import { LoaderCircle } from 'lucide-react'
import type { Health } from '../types'

const LABELS: [key: string, label: string][] = [
  ['neo4j', 'Neo4j'],
  ['apoc', 'APOC'],
  ['indexes', 'Indexes'],
  ['ollama', 'Ollama'],
  ['llm', 'LLM'],
  ['embedder', 'Embeddings'],
]

interface Props {
  health: Health | undefined
  error: Error | null
}

export function StatusBar({ health, error }: Props) {
  if (error && !health) {
    return (
      <div className="status-bar">
        <span className="pill bad" title={error.message}>
          <span className="dot" /> API offline
        </span>
      </div>
    )
  }
  if (!health) {
    return (
      <div className="status-bar">
        <span className="pill">
          <LoaderCircle size={12} className="spin" /> Checking system…
        </span>
      </div>
    )
  }

  const { components, models, ingestion } = health
  return (
    <div className="status-bar">
      {ingestion.current && (
        <span className="pill busy" title={`${ingestion.queued} more in queue`}>
          <LoaderCircle size={12} className="spin" />
          {ingestion.current.file_name}: {ingestion.current.stage}
          {ingestion.queued > 0 && ` (+${ingestion.queued})`}
        </span>
      )}
      {LABELS.map(([key, label]) => {
        const c = components[key]
        const name = key === 'llm' ? models.llm : key === 'embedder' ? models.embedder : label
        return (
          <span key={key} className={`pill ${c?.ok ? 'ok' : 'bad'}`} title={c?.detail ?? 'Unknown'}>
            <span className="dot" />
            {name}
          </span>
        )
      })}
    </div>
  )
}
