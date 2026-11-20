import { useEffect, useState } from 'react'
import { api, errorMessage, type HistoryEntry } from './api'

const pageSize = 20
const date = new Intl.DateTimeFormat('es-CU', { dateStyle: 'short', timeStyle: 'short' })
const labels = { query: 'Consulta', generation: 'Generación' } as const

export function Historial() {
  const [request, setRequest] = useState({ offset: 0 })
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null)
  const [error, setError] = useState('')
  const { offset } = request
  const loading = entries === null && !error

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

  function load(nextOffset: number) {
    setEntries(null)
    setError('')
    setRequest({ offset: nextOffset })
  }

  return (
    <>
      <h1>Historial</h1>
      {loading && <p role="status" className="loading">Cargando el historial…</p>}
      {error && (
        <>
          <p className="status error" role="alert">{error}</p>
          <button type="button" className="secondary" onClick={() => load(offset)}>Reintentar</button>
        </>
      )}
      {entries?.length === 0 && (
        <p role="status" className="empty">{offset === 0 ? 'Todavía no tienes consultas ni generaciones.' : 'No hay más entradas.'}</p>
      )}
      {entries && entries.length > 0 && (
        <div className="table-wrap" role="region" aria-label="Actividad reciente" tabIndex={0}>
          <table>
            <caption>Actividad reciente</caption>
            <thead>
              <tr><th scope="col">Fecha</th><th scope="col">Acción</th><th scope="col">Resumen</th></tr>
            </thead>
            <tbody>
              {entries.slice(0, pageSize).map((entry) => (
                <tr key={entry.id}>
                  <td><time dateTime={entry.created_at}>{date.format(new Date(entry.created_at))}</time></td>
                  <td><span className={`badge ${entry.action}`}>{labels[entry.action]}</span></td>
                  <td>{entry.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(offset > 0 || (entries && entries.length > pageSize)) && (
        <div className="actions pager" role="group" aria-label="Paginación del historial">
          <button type="button" className="secondary" disabled={loading || offset === 0} onClick={() => load(offset - pageSize)}>Anterior</button>
          <button type="button" className="secondary" disabled={!entries || entries.length <= pageSize} onClick={() => load(offset + pageSize)}>Siguiente</button>
        </div>
      )}
    </>
  )
}
