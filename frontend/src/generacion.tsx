import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, formatLabels as formats, type Answer, type Citation, type GenerationFormat, type GenerationRequest } from './api'
import { Citations, MarkedText } from './consulta'
import { CorpusOptions } from './CorpusOptions'

type Marked = { citas: Citation[]; onSelect: (position: number) => void }

export function Generacion() {
  const [state, setState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [subject, setSubject] = useState('')
  const focusRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (state === 'done' || state === 'error') focusRef.current?.focus()
  }, [state])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const text = (name: string) => String(data.get(name) ?? '').trim() || undefined
    const year = text('year')
    const body: GenerationRequest = {
      format: data.get('format') as GenerationFormat,
      prompt: text('prompt') ?? '',
      year: year ? Number(year) : undefined,
      subject: text('subject'),
      topic: text('topic'),
    }
    setState('loading')
    setSelected(null)
    try {
      setAnswer(await api<Answer>('/generations', { method: 'POST', body: JSON.stringify(body) }))
      setState('done')
    } catch (err) {
      setError(errorMessage(err))
      setState('error')
    }
  }

  const marked: Marked | null = answer && { citas: answer.citations, onSelect: setSelected }

  return (
    <>
      <h1>Generación de material</h1>
      <form className="card" onSubmit={submit} aria-busy={state === 'loading'}>
        <fieldset className="options">
          <legend>Formato</legend>
          {Object.entries(formats).map(([value, label]) => (
            <label key={value} className="choice">
              <input type="radio" name="format" value={value} defaultChecked={value === 'summary'} /> {label}
            </label>
          ))}
        </fieldset>
        <p className="note">Año, asignatura y tema son opcionales y acotan la búsqueda en el corpus.</p>
        <div className="fields">
          <label>
            Año
            <select name="year" defaultValue="">
              <option value="">Todos</option>
              {[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value}.º año</option>)}
            </select>
          </label>
          <label>
            Asignatura
            <input name="subject" list="gen-asignaturas" maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} />
          </label>
          <label>
            Tema
            <input name="topic" list="gen-temas" maxLength={200} />
          </label>
        </div>
        <CorpusOptions subjectsId="gen-asignaturas" topicsId="gen-temas" subject={subject} />
        <label>
          Contenido a sintetizar (tema o pregunta)
          <textarea
            name="prompt" required maxLength={1000} rows={3}
            aria-describedby={state === 'error' ? 'generacion-error' : undefined}
          />
        </label>
        <button type="submit" disabled={state === 'loading'}>Generar</button>
      </form>

      <p role="status" className="loading">{state === 'loading' ? 'Generando a partir del corpus…' : ''}</p>

      {state === 'idle' && <p className="empty">Aún no has generado material.</p>}

      {state === 'error' && (
        <p id="generacion-error" className="status error" role="alert" tabIndex={-1} ref={(el) => { focusRef.current = el }}>{error}</p>
      )}

      {state === 'done' && answer && marked && (
        <section aria-labelledby="generado" className="result">
          <h2 id="generado" tabIndex={-1} ref={(el) => { focusRef.current = el }}>
            {answer.status === 'answered' ? formats[answer.kind as GenerationFormat] : 'Sin evidencia en el corpus'}
          </h2>
          {answer.status === 'no_evidence'
            ? <p className="status">{answer.content || 'El corpus no contiene material que respalde este contenido.'}</p>
            : <Material answer={answer} {...marked} />}
          {answer.citations.length > 0 && <Citations citas={answer.citations} selected={selected} onSelect={setSelected} />}
          <Link className="feedback-link" to={`/feedback?answer_id=${answer.id}`}>Enviar feedback de esta respuesta</Link>
        </section>
      )}
    </>
  )
}

const lines = (content: string) => content.split('\n').filter((line) => line.trim())

/** Renderiza `content` según la estructura del formato (docs/api-contract.md, CU-02). */
export function Material({ answer, ...marked }: { answer: Answer } & Marked) {
  const rows = lines(answer.content)
  if (answer.kind === 'outline') return <Outline items={outline(rows)} {...marked} />
  if (answer.kind === 'table') return <Table rows={rows} caption={answer.question} {...marked} />
  if (answer.kind === 'diagram') return <Diagram rows={rows} caption={answer.question} {...marked} />
  return rows.map((row, i) => <p key={i} className="answer"><MarkedText text={row} {...marked} /></p>)
}

type Item = { text: string; children: Item[] }

function outline(rows: string[]): Item[] {
  const root: Item[] = []
  const stack = [root]
  for (const row of rows) {
    const match = /^((?: {2})*)- (.*)$/.exec(row) ?? ['', '', row.trim()]
    // El backend ya valida la sangría; aquí solo se acota por si acaso.
    const level = Math.min(match[1].length / 2, stack.length - 1)
    const item = { text: match[2], children: [] }
    stack[level].push(item)
    stack.length = level + 1
    stack.push(item.children)
  }
  return root
}

function Outline({ items, ...marked }: { items: Item[] } & Marked) {
  return (
    <ul className="outline">
      {items.map((item, i) => (
        <li key={i}>
          <MarkedText text={item.text} {...marked} />
          {item.children.length > 0 && <Outline items={item.children} {...marked} />}
        </li>
      ))}
    </ul>
  )
}

function Table({ rows, caption, ...marked }: { rows: string[]; caption: string } & Marked) {
  const [header, , ...body] = rows.map((row) => row.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim()))
  return (
    <div className="table-wrap" role="region" aria-label={caption} tabIndex={0}>
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>{header.map((cell, i) => <th key={i} scope="col">{cell}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((row, r) => (
            <tr key={r}>
              {row.map((cell, i) => i === 0
                ? <th key={i} scope="row"><MarkedText text={cell} {...marked} /></th>
                : <td key={i}><MarkedText text={cell} {...marked} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Diagram({ rows, caption, ...marked }: { rows: string[]; caption: string } & Marked) {
  const edges = rows.map((row) => {
    const [from, rest] = row.split(/ -> (.*)/)
    const [to, label] = (rest ?? '').split(/: (.*)/)
    return { from: from.trim(), to: to.trim(), label }
  })
  return (
    <figure className="diagram">
      {/* Dibujo solo visual; la lista de relaciones es la alternativa textual con las citas. */}
      <pre aria-hidden="true">
        {edges.map(({ from, to, label }) => `${from} ──${label ? `(${label})──` : ''}▶ ${to}`).join('\n')}
      </pre>
      <figcaption>
        Relaciones de «{caption}»:
        <ol>
          {edges.map(({ from, to, label }, i) => (
            <li key={i}><MarkedText text={`${from} → ${to}${label ? `: ${label}` : ''}`} {...marked} /></li>
          ))}
        </ol>
      </figcaption>
    </figure>
  )
}
