import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, type Answer, type Citation, type Page, type QueryRequest } from './api'
import { CorpusOptions } from './CorpusOptions'

const pageName = (cita: Citation) => `p. ${cita.page_label ?? cita.page_number}`

export function Consulta() {
  const [state, setState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [subject, setSubject] = useState('')
  const focusRef = useRef<HTMLElement>(null)

  // Lleva el foco al resultado o al error cuando llega la respuesta.
  useEffect(() => {
    if (state === 'done' || state === 'error') focusRef.current?.focus()
  }, [state])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const text = (name: string) => String(data.get(name) ?? '').trim() || undefined
    const year = text('year')
    const body: QueryRequest = { year: year ? Number(year) : undefined, subject: text('subject'), topic: text('topic'), question: text('question') ?? '' }
    setState('loading')
    setSelected(null)
    try {
      setAnswer(await api<Answer>('/queries', { method: 'POST', body: JSON.stringify(body) }))
      setState('done')
    } catch (err) {
      setError(errorMessage(err))
      setState('error')
    }
  }

  return (
    <>
      <h1>Consulta</h1>
      <form className="card" onSubmit={submit} aria-busy={state === 'loading'}>
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
            <input name="subject" list="asignaturas" maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} />
          </label>
          <label>
            Tema
            <input name="topic" list="temas" maxLength={200} />
          </label>
        </div>
        <CorpusOptions subjectsId="asignaturas" topicsId="temas" subject={subject} />
        <label>
          Pregunta
          <textarea
            name="question" required maxLength={1000} rows={3}
            aria-describedby={state === 'error' ? 'consulta-error' : undefined}
          />
        </label>
        <button type="submit" disabled={state === 'loading'}>Consultar</button>
      </form>

      <p role="status" className="loading">{state === 'loading' ? 'Consultando el corpus…' : ''}</p>

      {state === 'idle' && <p className="empty">Aún no has hecho ninguna consulta.</p>}

      {state === 'error' && (
        <p id="consulta-error" className="status error" role="alert" tabIndex={-1} ref={(el) => { focusRef.current = el }}>{error}</p>
      )}

      {state === 'done' && answer && (
        <section aria-labelledby="respuesta" className="result">
          <h2 id="respuesta" tabIndex={-1} ref={(el) => { focusRef.current = el }}>
            {answer.status === 'answered' ? 'Respuesta' : 'Sin evidencia en el corpus'}
          </h2>
          {answer.status === 'no_evidence'
            ? <p className="status">{answer.content || 'El corpus no contiene material que respalde una respuesta.'}</p>
            : <AnswerText answer={answer} onSelect={setSelected} />}
          {answer.citations.length > 0 && <Citations citas={answer.citations} selected={selected} onSelect={setSelected} />}
          <Link className="feedback-link" to={`/feedback?answer_id=${answer.id}`}>Enviar feedback de esta respuesta</Link>
        </section>
      )}
    </>
  )
}

function AnswerText({ answer, onSelect }: { answer: Answer; onSelect: (position: number) => void }) {
  return <p className="answer"><MarkedText text={answer.content} citas={answer.citations} onSelect={onSelect} /></p>
}

/** Muestra el texto convirtiendo las marcas [n] en botones que abren la cita n. */
export function MarkedText({ text, citas, onSelect }: { text: string; citas: Citation[]; onSelect: (position: number) => void }) {
  return text.split(/\[(\d+)\]/).map((part, i) => {
    if (i % 2 === 0) return part
    const cita = citas.find((c) => c.position === Number(part))
    if (!cita) return `[${part}]`
    return (
      <button key={i} type="button" className="link marker" aria-label={`Cita ${part}: ${cita.document_title}, ${pageName(cita)}`} onClick={() => onSelect(cita.position)}>
        [{part}]
      </button>
    )
  })
}

export function Citations({ citas, selected, onSelect }: { citas: Citation[]; selected: number | null; onSelect: (position: number | null) => void }) {
  const open = citas.find((c) => c.position === selected)
  return (
    <section aria-labelledby="fuentes">
      <h2 id="fuentes">Fuentes</h2>
      <ol className="citations">
        {citas.map((cita) => (
          <li key={cita.position}>
            <button type="button" className="link" aria-expanded={cita === open} aria-controls="visor-cita" onClick={() => onSelect(cita === open ? null : cita.position)}>
              <span className="cite-num">[{cita.position}]</span> <span className="cite-title">{cita.document_title},</span> <span className="cite-page">{pageName(cita)}</span>
            </button>
          </li>
        ))}
      </ol>
      {open && <CitationViewer key={open.position} cita={open} />}
    </section>
  )
}

function CitationViewer({ cita }: { cita: Citation }) {
  const [page, setPage] = useState<Page | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [error, setError] = useState('')
  const headingRef = useRef<HTMLHeadingElement>(null)
  const markRef = useRef<HTMLElement>(null)
  const pageRef = useRef<HTMLDivElement>(null)

  useEffect(() => headingRef.current?.focus(), [])
  // Al cargar la página, el foco pasa a su texto (el botón desaparece) y se muestra el fragmento resaltado.
  useEffect(() => {
    pageRef.current?.focus()
    markRef.current?.scrollIntoView({ block: 'nearest' })
  }, [page])

  async function loadPage() {
    setState('loading')
    try {
      setPage(await api<Page>(`/documents/${encodeURIComponent(cita.document_id)}/pages/${cita.page_number}`))
      setState('idle')
    } catch (err) {
      setError(errorMessage(err))
      setState('error')
    }
  }

  const sameVersion = page?.version === cita.document_version
  const matches = sameVersion && page.text.slice(cita.start, cita.end) === cita.quote

  return (
    <div id="visor-cita" className="viewer">
      <h3 tabIndex={-1} ref={headingRef}>Cita [{cita.position}]</h3>
      <dl>
        <dt>Documento</dt><dd>{cita.document_title}</dd>
        <dt>Versión</dt><dd><code title={cita.document_version}>{cita.document_version.slice(0, 12)}</code></dd>
        <dt>Página</dt><dd>{cita.page_number}{cita.page_label && ` (impresa: ${cita.page_label})`}</dd>
      </dl>
      <blockquote className="source"><p>{cita.quote}</p></blockquote>
      {!page && (
        <button type="button" className="secondary" onClick={loadPage} disabled={state === 'loading'} aria-describedby={state === 'error' ? 'visor-error' : undefined}>
          Ver en la página
        </button>
      )}
      <p role="status" className="loading">{state === 'loading' ? 'Cargando la página…' : ''}</p>
      {state === 'error' && <p id="visor-error" className="status error" role="alert">{error}</p>}
      {page && (
        <>
          {!sameVersion && <p className="status warning">El documento se ha actualizado desde esta cita; la página vigente puede no contener el texto citado.</p>}
          {sameVersion && !matches && <p className="status warning">El texto de la página no coincide con la cita guardada.</p>}
          {page.status === 'no_text' && <p className="note">La página no tiene texto extraíble.</p>}
          <div className="page" tabIndex={0} ref={pageRef} aria-label={`Texto de la página ${page.number}`}>
            {matches ? (
              <>
                {page.text.slice(0, cita.start)}
                <mark ref={markRef}>{cita.quote}</mark>
                {page.text.slice(cita.end)}
              </>
            ) : page.text}
          </div>
        </>
      )}
    </div>
  )
}
