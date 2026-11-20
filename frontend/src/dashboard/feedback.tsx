import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { AdminFeedback } from '../admin-api'
import { dateTime, feedbackLabels, pageSize } from './labels'
import { ListState, Pager, UserCell } from './shared'
import { useApi } from './useApi'

export function FeedbackAdmin() {
  const [query, setQuery] = useState({ kind: '', offset: 0 })
  const search = new URLSearchParams({ limit: String(pageSize + 1), offset: String(query.offset) })
  if (query.kind) search.set('kind', query.kind)
  const { data: rows, error, loading, reload } = useApi<AdminFeedback[]>(`/admin/feedback?${search}`)

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setQuery({ kind: String(new FormData(event.currentTarget).get('kind') ?? ''), offset: 0 })
  }

  return (
    <section className="card" aria-labelledby="feedback-lista">
      <h2 id="feedback-lista">Feedback recibido</h2>
      <form onSubmit={filter} aria-label="Filtrar feedback">
        <div className="fields">
          <label>
            Tipo
            <select name="kind" defaultValue="">
              <option value="">Todos</option>
              {Object.entries(feedbackLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        <button type="submit" className="secondary">Filtrar</button>
      </form>

      <ListState loading={loading} error={error} empty={rows?.length === 0} onRetry={reload} what="feedback" />
      {rows && rows.length > 0 && (
        <div className="table-wrap" role="region" aria-label="Feedback" tabIndex={0}>
          <table>
            <caption>Feedback de todas las cuentas</caption>
            <thead>
              <tr>
                <th scope="col">Comentario</th><th scope="col">Tipo</th><th scope="col">Valoración</th>
                <th scope="col">Sobre</th><th scope="col">Cuenta</th><th scope="col">Fecha</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, pageSize).map((row) => (
                <tr key={row.id}>
                  <td className="wrap">{row.comment || <span className="note">Sin comentario</span>}</td>
                  <td><span className={`badge ${row.kind === 'error' ? 'danger' : row.kind === 'rating' ? 'query' : ''}`}>{feedbackLabels[row.kind]}</span></td>
                  <td>{row.rating === null ? '—' : <span aria-label={`${row.rating} de 5`}>{row.rating}/5</span>}</td>
                  <td>
                    {row.answer_id !== null && <Link to={`/dashboard?tab=consultas&answer=${row.answer_id}`}>Respuesta {row.answer_id}</Link>}
                    {row.exam_id !== null && <>Examen {row.exam_id}</>}
                    {row.answer_id === null && row.exam_id === null && '—'}
                  </td>
                  <td><UserCell user={row.user} /></td>
                  <td><time dateTime={row.created_at}>{dateTime.format(new Date(row.created_at))}</time></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager offset={query.offset} rows={rows} onChange={(offset) => setQuery({ ...query, offset })} label="Paginación del feedback" />
    </section>
  )
}
