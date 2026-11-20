import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, type HistoryEntry } from './api'

const pageSize = 20
const date = new Intl.DateTimeFormat('es-CU', { dateStyle: 'short', timeStyle: 'short' })
const labels = { query: 'Consulta', generation: 'Generación' } as const

type Confirmation = { kind: 'one'; entry: HistoryEntry } | { kind: 'all' }

export function Historial() {
  const [request, setRequest] = useState({ offset: 0 })
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [confirm, setConfirm] = useState<Confirmation | null>(null)
  const [busy, setBusy] = useState(false)
  const { offset } = request
  const loading = entries === null && !error
  const dialogRef = useRef<HTMLDialogElement>(null)
  const noticeRef = useRef<HTMLParagraphElement>(null)
  const errorRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    api<HistoryEntry[]>(`/history?limit=${pageSize + 1}&offset=${request.offset}`, {
      signal: controller.signal,
    })
      .then((rows) => {
        if (!controller.signal.aborted) setEntries(rows)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
    return () => controller.abort()
  }, [request])

  useEffect(() => {
    const dialog = dialogRef.current
    if (confirm && !dialog?.open) dialog?.showModal()
    if (!confirm && dialog?.open) dialog.close()
  }, [confirm])

  useEffect(() => {
    if (notice) noticeRef.current?.focus()
  }, [notice])

  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  function load(nextOffset: number) {
    setEntries(null)
    setError('')
    setRequest({ offset: nextOffset })
  }

  async function remove() {
    if (!confirm) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (confirm.kind === 'all') {
        await api<void>('/history', { method: 'DELETE' })
        setConfirm(null)
        setNotice('Historial eliminado.')
        load(0)
      } else {
        await api<void>(`/history/${confirm.entry.id}`, { method: 'DELETE' })
        setConfirm(null)
        setNotice('Entrada eliminada.')
        const remaining = (entries?.length ?? 1) - 1
        load(remaining <= 0 && offset > 0 ? offset - pageSize : offset)
      }
    } catch (err) {
      setConfirm(null)
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h1>Historial</h1>
      <div className="actions">
        <button
          type="button"
          className="secondary"
          disabled={busy || !entries?.length}
          onClick={() => setConfirm({ kind: 'all' })}
        >
          Borrar todo el historial
        </button>
      </div>

      {notice && (
        <p role="status" className="status ok" tabIndex={-1} ref={noticeRef}>{notice}</p>
      )}
      {loading && <p role="status">Cargando el historial…</p>}
      {error && (
        <>
          <p className="status error" role="alert" tabIndex={-1} ref={errorRef}>{error}</p>
          <button type="button" onClick={() => load(offset)}>Reintentar</button>
        </>
      )}
      {entries?.length === 0 && (
        <p role="status">{offset === 0 ? 'Todavía no tienes consultas ni generaciones.' : 'No hay más entradas.'}</p>
      )}
      {entries && entries.length > 0 && (
        <table>
          <caption>Actividad reciente</caption>
          <thead>
            <tr>
              <th scope="col">Fecha</th><th scope="col">Acción</th><th scope="col">Resumen</th>
              <th scope="col">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {entries.slice(0, pageSize).map((entry) => (
              <tr key={entry.id}>
                <td><time dateTime={entry.created_at}>{date.format(new Date(entry.created_at))}</time></td>
                <td>{labels[entry.action]}</td>
                <td>{entry.summary}</td>
                <td>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    aria-label={`Eliminar ${labels[entry.action].toLowerCase()}: ${entry.summary}`}
                    onClick={() => setConfirm({ kind: 'one', entry })}
                  >
                    Eliminar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(offset > 0 || (entries && entries.length > pageSize)) && (
        <div className="fields" role="group" aria-label="Paginación del historial">
          <button type="button" disabled={busy || loading || offset === 0} onClick={() => load(offset - pageSize)}>Anterior</button>
          <button type="button" disabled={busy || !entries || entries.length <= pageSize} onClick={() => load(offset + pageSize)}>Siguiente</button>
        </div>
      )}

      <dialog
        ref={dialogRef}
        aria-labelledby="history-confirm-title"
        aria-describedby="history-confirm-text"
        onClose={() => setConfirm(null)}
      >
        {confirm && (
          <>
            <h2 id="history-confirm-title">
              {confirm.kind === 'all' ? 'Borrar todo el historial' : 'Eliminar del historial'}
            </h2>
            <p id="history-confirm-text">
              {confirm.kind === 'all'
                ? 'Se borrarán todas tus consultas y generaciones con sus respuestas. Esta acción no se puede deshacer.'
                : `Se borrarán «${confirm.entry.summary}» y su respuesta. Esta acción no se puede deshacer.`}
            </p>
            <div className="actions">
              <button type="button" className="secondary" autoFocus disabled={busy} onClick={() => setConfirm(null)}>
                Cancelar
              </button>
              <button type="button" disabled={busy} onClick={remove}>
                {busy ? 'Eliminando…' : 'Eliminar'}
              </button>
            </div>
          </>
        )}
      </dialog>
    </>
  )
}
