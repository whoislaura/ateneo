import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type Answer, type Citation, type Page, type QueryRequest } from './api'
import { asignaturas } from './mock'

function errorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return 'No se pudo conectar con el servidor. Comprueba la conexión e inténtalo de nuevo.'
  if (err.status === 401) return 'Tu sesión ha caducado.'
  if (err.status === 403) return 'Tu rol no tiene permiso para esta acción.'
  if (err.status === 404) return 'El recurso solicitado no existe o ya no está disponible.'
  if (err.status === 422) return 'Revisa los datos: hay campos no válidos.'
  if (err.status === 501) return 'Esta función aún no está disponible en el servidor.'
  return err.message
}

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

  const temas = asignaturas.find((a) => a.nombre === subject)?.temas ?? asignaturas.flatMap((a) => a.temas)

  return (
    <>
      <h1>Consulta</h1>
      <form onSubmit={submit} aria-busy={state === 'loading'}>
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
        {/* shortcut: sugerencias de mock.ts; sustituir por las clasificaciones de GET /documents cuando exista (AT-10). */}
        <datalist id="asignaturas">{asignaturas.map((a) => <option key={a.nombre} value={a.nombre} />)}</datalist>
        <datalist id="temas">{temas.map((t) => <option key={t} value={t} />)}</datalist>
        <label>
          Pregunta
          <textarea
            name="question" required maxLength={1000} rows={3}
            aria-describedby={state === 'error' ? 'consulta-error' : undefined}
          />
        </label>
        <button type="submit" disabled={state === 'loading'}>Consultar</button>
      </form>

      <p role="status" className="note">{state === 'loading' ? 'Consultando el corpus…' : ''}</p>

      {state === 'idle' && <p className="note">Aún no has hecho ninguna consulta.</p>}

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
        </section>
      )}
    </>
  )
}

/** Muestra el contenido convirtiendo las marcas [n] en botones que abren la cita n. */
function AnswerText({ answer, onSelect }: { answer: Answer; onSelect: (position: number) => void }) {
  const parts = answer.content.split(/\[(\d+)\]/)
  return (
    <p className="answer">
      {parts.map((part, i) => {
        if (i % 2 === 0) return part
        const cita = answer.citations.find((c) => c.position === Number(part))
        if (!cita) return `[${part}]`
        return (
          <button key={i} type="button" className="link marker" aria-label={`Cita ${part}: ${cita.document_title}, ${pageName(cita)}`} onClick={() => onSelect(cita.position)}>
            [{part}]
          </button>
        )
      })}
    </p>
  )
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
              [{cita.position}] {cita.document_title}, {pageName(cita)}
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
        <button type="button" onClick={loadPage} disabled={state === 'loading'} aria-describedby={state === 'error' ? 'visor-error' : undefined}>
          Ver en la página
        </button>
      )}
      <p role="status" className="note">{state === 'loading' ? 'Cargando la página…' : ''}</p>
      {state === 'error' && <p id="visor-error" className="status error" role="alert">{error}</p>}
      {page && (
        <>
          {!sameVersion && <p className="status error">El documento se ha actualizado desde esta cita; la página vigente puede no contener el texto citado.</p>}
          {sameVersion && !matches && <p className="status error">El texto de la página no coincide con la cita guardada.</p>}
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
