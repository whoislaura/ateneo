import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import type { Answer } from '../api'
import type { AdminAnswer } from '../admin-api'
import { Citations, MarkedText } from '../consulta'
import { Material } from '../generacion'
import { answerStatusLabels, dateTime, kindLabels, pageSize } from './labels'
import { ListState, Pager, UserCell } from './shared'
import { useApi } from './useApi'

export function Consultas() {
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState({ kind: '', status: '', offset: 0 })
  const search = new URLSearchParams({ limit: String(pageSize + 1), offset: String(query.offset) })
  if (query.kind) search.set('kind', query.kind)
  if (query.status) search.set('status', query.status)
  const { data: rows, error, loading, reload } = useApi<AdminAnswer[]>(`/admin/answers?${search}`)
  const listRef = useRef<HTMLHeadingElement>(null)
  // El detalle abierto vive en la URL (?tab=consultas&answer=ID): sobrevive a recargar y el feedback enlaza aquí.
  const answerId = params.get('answer')

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setQuery({ kind: String(data.get('kind') ?? ''), status: String(data.get('status') ?? ''), offset: 0 })
  }

  function show(id: number | null) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (id === null) next.delete('answer')
      else next.set('answer', String(id))
      return next
    }, { replace: true })
    if (id === null) listRef.current?.focus()
  }

  return (
    <>
      {answerId && <AnswerDetail key={answerId} id={answerId} onClose={() => show(null)} />}

      <section className="card" aria-labelledby="consultas-lista">
        <h2 id="consultas-lista" tabIndex={-1} ref={listRef}>Consultas y generaciones</h2>
        <form onSubmit={filter} aria-label="Filtrar consultas y generaciones">
          <div className="fields">
            <label>
              Tipo
              <select name="kind" defaultValue="">
                <option value="">Todos</option>
                {Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>
              Estado
              <select name="status" defaultValue="">
                <option value="">Todos</option>
                {Object.entries(answerStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </div>
          <button type="submit" className="secondary">Filtrar</button>
        </form>

        <ListState loading={loading} error={error} empty={rows?.length === 0} onRetry={reload} what="consultas ni generaciones" />
        {rows && rows.length > 0 && (
          <div className="table-wrap" role="region" aria-label="Consultas y generaciones" tabIndex={0}>
            <table>
              <caption>Consultas y generaciones de todas las cuentas</caption>
              <thead>
                <tr>
                  <th scope="col">Pregunta</th><th scope="col">Tipo</th><th scope="col">Estado</th><th scope="col">Citas</th>
                  <th scope="col">Cuenta</th><th scope="col">Fecha</th><th scope="col">Detalle</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, pageSize).map((row) => (
                  <tr key={row.id} aria-current={String(row.id) === answerId || undefined}>
                    <th scope="row">{row.question}</th>
                    <td><span className={`badge ${row.kind === 'query' ? 'query' : 'generation'}`}>{kindLabels[row.kind]}</span></td>
                    <td><span className={`badge ${row.status === 'answered' ? 'success' : 'warning'}`}>{answerStatusLabels[row.status]}</span></td>
                    <td>{row.citations}</td>
                    <td><UserCell user={row.user} /></td>
                    <td><time dateTime={row.created_at}>{dateTime.format(new Date(row.created_at))}</time></td>
                    <td>
                      <button type="button" className="secondary small" onClick={() => show(row.id)} aria-label={`Ver respuesta ${row.id}: ${row.question}`}>Ver</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager offset={query.offset} rows={rows} onChange={(offset) => setQuery({ ...query, offset })} label="Paginación de consultas" />
      </section>
    </>
  )
}

/** Respuesta completa con el mismo renderizado y visor de citas que Consulta y Generación. */
function AnswerDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: answer, error, loading, reload } = useApi<Answer>(`/admin/answers/${encodeURIComponent(id)}`)
  const [selected, setSelected] = useState<number | null>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (answer || error) headingRef.current?.focus()
  }, [answer, error])

  return (
    <section className="result" aria-labelledby="detalle-respuesta">
      <h2 id="detalle-respuesta" tabIndex={-1} ref={headingRef}>
        {answer ? `${kindLabels[answer.kind]} ${answer.id}` : `Respuesta ${id}`}
      </h2>
      <ListState loading={loading} error={error} empty={false} onRetry={reload} what="la respuesta" />
      {answer && (
        <>
          <dl className="meta">
            <dt>Pregunta</dt><dd>{answer.question}</dd>
            <dt>Fecha</dt><dd><time dateTime={answer.created_at}>{dateTime.format(new Date(answer.created_at))}</time></dd>
            {(answer.year || answer.subject || answer.topic) && (
              <><dt>Filtros</dt><dd>{[answer.year && `${answer.year}.º año`, answer.subject, answer.topic].filter(Boolean).join(' · ')}</dd></>
            )}
          </dl>
          {answer.status === 'no_evidence'
            ? <p className="status">{answer.content || 'El corpus no contiene material que respalde una respuesta.'}</p>
            : answer.kind === 'query'
              ? <p className="answer"><MarkedText text={answer.content} citas={answer.citations} onSelect={setSelected} /></p>
              : <Material answer={answer} citas={answer.citations} onSelect={setSelected} />}
          {answer.citations.length > 0 && <Citations citas={answer.citations} selected={selected} onSelect={setSelected} />}
        </>
      )}
      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>Cerrar detalle</button>
      </div>
    </section>
  )
}
