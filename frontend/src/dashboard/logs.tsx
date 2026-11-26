import { useEffect, useState, type FormEvent } from 'react'
import type { LogEntry } from '../admin-api'
import { ListState } from './shared'
import { useApi } from './useApi'

const time = new Intl.DateTimeFormat('es-CU', { dateStyle: 'short', timeStyle: 'medium' })
const levelBadge = (level: string) => (level === 'ERROR' || level === 'CRITICAL' ? 'danger' : level === 'WARNING' ? 'warning' : '')

export function Logs() {
  const [query, setQuery] = useState({ level: '', q: '' })
  const [auto, setAuto] = useState(false)
  const search = new URLSearchParams({ limit: '200' })
  if (query.level) search.set('level', query.level)
  if (query.q) search.set('q', query.q)
  const { data: rows, error, loading, reload, inflight } = useApi<LogEntry[]>(`/admin/logs?${search}`)

  useEffect(() => {
    if (!auto) return
    // Salta el ciclo con la pestaña oculta o una petición aún en vuelo.
    const id = setInterval(() => { if (!document.hidden && !inflight.current) reload() }, 10_000)
    return () => clearInterval(id)
  }, [auto, reload, inflight])

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setQuery({ level: String(data.get('level') ?? ''), q: String(data.get('q') ?? '').trim() })
  }

  return (
    <section className="card" aria-labelledby="logs-lista">
      <h2 id="logs-lista">Registro de la aplicación</h2>
      <p className="note">
        Muestra las últimas 1000 entradas del proceso actual del servidor (se pierden al reiniciar). Los logs completos siguen en la salida estándar del servicio.
      </p>
      <form onSubmit={filter} aria-label="Filtrar el registro">
        <div className="fields">
          <label>
            Nivel mínimo
            <select name="level" defaultValue="">
              <option value="">Todos</option>
              <option value="INFO">Información</option>
              <option value="WARNING">Aviso</option>
              <option value="ERROR">Error</option>
            </select>
          </label>
          <label>Buscar en mensaje, ruta o ID de petición<input name="q" type="search" maxLength={200} /></label>
        </div>
        <div className="actions">
          <button type="submit" className="secondary">Filtrar</button>
          <button type="button" className="secondary" onClick={reload}>Actualizar</button>
          <label className="choice">
            <input type="checkbox" checked={auto} onChange={(event) => setAuto(event.target.checked)} /> Actualizar cada 10 s
          </label>
        </div>
      </form>

      <ListState loading={loading} error={error} empty={rows?.length === 0} onRetry={reload} what="entradas" />
      {rows && rows.length > 0 && (
        <div className="table-wrap" role="region" aria-label="Entradas del registro" tabIndex={0}>
          <table>
            <caption>Entradas recientes ({rows.length}), de la más reciente a la más antigua</caption>
            <thead>
              <tr>
                <th scope="col">Hora</th><th scope="col">Nivel</th><th scope="col">Mensaje</th>
                <th scope="col">Petición</th><th scope="col">ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.ts}-${i}`}>
                  <td><time dateTime={row.ts}>{time.format(new Date(row.ts))}</time></td>
                  <td><span className={`badge ${levelBadge(row.level)}`}>{row.level}</span></td>
                  <td className="wrap">
                    {row.message}
                    <br /><span className="note">{row.logger}</span>
                    {row.exception && (
                      <details className="log-exception">
                        <summary>Ver excepción</summary>
                        <pre>{row.exception}</pre>
                      </details>
                    )}
                  </td>
                  <td>
                    {row.path ? <code>{row.method} {row.path}</code> : '—'}
                    {row.status !== undefined && <><br /><span className="note">{row.status}{row.duration_ms !== undefined && ` · ${row.duration_ms} ms`}</span></>}
                  </td>
                  <td>{row.request_id ? <code>{row.request_id}</code> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
