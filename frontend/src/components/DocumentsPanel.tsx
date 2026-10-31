import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, Clock, FileText, LoaderCircle, Upload, X } from 'lucide-react'
import { useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { api } from '../api'
import { fileSize, timeAgo } from '../format'
import type { DocumentInfo } from '../types'

interface Props {
  documents: DocumentInfo[] | undefined
  loading: boolean
  selectedId: string | null
  onSelect: (id: string | null) => void
}

const STATUS_ICON = {
  queued: <Clock size={14} />,
  processing: <LoaderCircle size={14} className="spin" />,
  done: <CircleCheck size={14} />,
  failed: <CircleAlert size={14} />,
}

export function DocumentsPanel({ documents, loading, selectedId, onSelect }: Props) {
  const queryClient = useQueryClient()
  const [errors, setErrors] = useState<string[]>([])

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const failed: string[] = []
      for (const file of files) {
        try {
          await api.upload(file)
        } catch (e) {
          failed.push(`${file.name}: ${(e as Error).message}`)
        }
        queryClient.invalidateQueries({ queryKey: ['documents'] })
      }
      return failed
    },
    onSuccess: (failed) => setErrors(failed),
  })

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    disabled: upload.isPending,
    onDrop: (accepted, rejected) => {
      setErrors(rejected.map((r) => `${r.file.name}: only PDF files are supported`))
      if (accepted.length) upload.mutate(accepted)
    },
  })

  return (
    <section className="panel documents">
      <header className="panel-header">
        <h2>Documents</h2>
        <span className="muted">{documents?.length ?? 0}</span>
      </header>

      <div {...getRootProps({ className: `dropzone${isDragActive ? ' active' : ''}` })}>
        <input {...getInputProps()} />
        {upload.isPending ? <LoaderCircle size={18} className="spin" /> : <Upload size={18} />}
        <span>{upload.isPending ? 'Uploading…' : isDragActive ? 'Drop PDFs here' : 'Drop PDFs or click to upload'}</span>
      </div>

      {errors.map((err) => (
        <div key={err} className="notice error small">
          <span>{err}</span>
          <button className="icon-btn" onClick={() => setErrors((e) => e.filter((x) => x !== err))} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      ))}

      <ul className="doc-list">
        {loading && !documents && <li className="muted small">Loading…</li>}
        {documents?.length === 0 && <li className="muted small">No documents yet. Upload a PDF to build the knowledge graph.</li>}
        {documents?.map((doc) => {
          const selectable = doc.status === 'done'
          const selected = selectedId === doc.id
          return (
            <li
              key={doc.id}
              className={`doc ${doc.status}${selected ? ' selected' : ''}${selectable ? ' selectable' : ''}`}
              onClick={() => selectable && onSelect(selected ? null : doc.id)}
              title={selectable ? (selected ? 'Show all documents in the graph' : 'Show only this document in the graph') : undefined}
            >
              <FileText size={16} className="doc-icon" />
              <div className="doc-body">
                <div className="doc-name">{doc.file_name}</div>
                <div className="doc-meta">
                  <span className={`badge ${doc.status}`}>
                    {STATUS_ICON[doc.status]} {doc.status}
                  </span>
                  {doc.status === 'done' && (
                    <span>
                      {doc.chunks} chunks · {doc.entities} entities
                    </span>
                  )}
                  {doc.status !== 'done' && <span>{fileSize(doc.file_size)}</span>}
                  <span className="muted">{timeAgo(doc.uploaded_at)}</span>
                </div>
                {doc.status === 'processing' && doc.stage && <div className="doc-stage">{doc.stage}…</div>}
                {doc.status === 'failed' && doc.error && <div className="doc-error">{doc.error}</div>}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
