import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api, errorMessage, type Answer, type ChatMessage, type Citation, type Conversation, type ConversationDetail, type Page, type Turn, type TurnRequest } from './api'
import { CorpusOptions } from './CorpusOptions'
import { citationRange, isSendKey } from './helpers'

const pageName = (cita: Citation) => `p. ${cita.page_label ?? cita.page_number}`
const pageSize = 20
const date = new Intl.DateTimeFormat('es-CU', { dateStyle: 'short', timeStyle: 'short' })

/** Elemento del hilo: un mensaje guardado, uno pendiente de confirmar o un error con su pregunta para reintentar. */
type Item =
  | { kind: 'message'; key: string; message: ChatMessage }
  | { kind: 'pending'; key: string; text: string }
  | { kind: 'error'; key: string; text: string; question: string }

const saved = (message: ChatMessage): Item => ({ kind: 'message', key: `m${message.id}`, message })

export function Consulta() {
  const [params, setParams] = useSearchParams()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [more, setMore] = useState(false)
  const [listError, setListError] = useState('')
  const [activeId, setActiveId] = useState<number | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [selected, setSelected] = useState<{ key: string; position: number } | null>(null)
  const [subject, setSubject] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busyDelete, setBusyDelete] = useState(false)
  const [notice, setNotice] = useState('')
  const formRef = useRef<HTMLFormElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const loadToken = useRef(0)
  const busy = thinking || loading

  useEffect(() => {
    const controller = new AbortController()
    api<Conversation[]>(`/conversations?limit=${pageSize + 1}`, { signal: controller.signal })
      .then((rows) => {
        if (controller.signal.aborted) return
        setConversations(rows.slice(0, pageSize))
        setMore(rows.length > pageSize)
      })
      .catch((err: unknown) => { if (!controller.signal.aborted) setListError(errorMessage(err)) })
    return () => controller.abort()
  }, [])

  // Abre la conversación de `?c=` (enlace del historial).
  const requested = Number(params.get('c'))
  useEffect(() => {
    if (Number.isInteger(requested) && requested > 0) {
      setParams({}, { replace: true })
      void open(requested)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested])

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }) }, [items, thinking])

  useEffect(() => {
    const dialog = dialogRef.current
    if (confirmDelete && !dialog?.open) dialog?.showModal()
    if (!confirmDelete && dialog?.open) dialog.close()
  }, [confirmDelete])

  async function open(id: number) {
    const token = ++loadToken.current
    setLoading(true)
    setNotice('')
    setSelected(null)
    try {
      const detail = await api<ConversationDetail>(`/conversations/${id}`)
      if (token !== loadToken.current) return
      setActiveId(id)
      setItems(detail.messages.map(saved))
    } catch (err) {
      if (token === loadToken.current) setNotice(errorMessage(err))
    } finally {
      if (token === loadToken.current) setLoading(false)
    }
  }

  function reset() {
    loadToken.current++
    setActiveId(null)
    setItems([])
    setSelected(null)
    setNotice('')
    inputRef.current?.focus()
  }

  async function send(question: string, filters: Omit<TurnRequest, 'question'>, retry = false) {
    setNotice('')
    setThinking(true)
    // La pregunta se ve de inmediato; el servidor la confirma (o el error ofrece reintentar).
    if (!retry) setItems((rows) => [...rows.filter((row) => row.kind === 'message'), { kind: 'pending', key: `p${Date.now()}`, text: question }])
    const body: TurnRequest = { question, ...filters }
    try {
      const turn = await api<Turn>(activeId === null ? '/conversations' : `/conversations/${activeId}/messages`, { method: 'POST', body: JSON.stringify(body) })
      setItems((rows) => [...rows.filter((row) => row.kind === 'message'), ...turn.messages.map(saved)])
      setActiveId(turn.conversation.id)
      setConversations((rows) => [turn.conversation, ...rows.filter((row) => row.id !== turn.conversation.id)])
    } catch (err) {
      setItems((rows) => [...rows.filter((row) => row.kind !== 'error'), { kind: 'error', key: `e${Date.now()}`, text: errorMessage(err), question }])
    } finally {
      setThinking(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const data = new FormData(event.currentTarget)
    const text = (name: string) => String(data.get(name) ?? '').trim() || undefined
    const question = text('question')
    if (!question) return
    const year = text('year')
    const filters = { year: year ? Number(year) : undefined, subject: text('subject'), topic: text('topic') }
    if (inputRef.current) inputRef.current.value = ''
    void send(question, filters)
  }

  function retry(question: string) {
    const form = formRef.current
    const year = (form?.elements.namedItem('year') as HTMLSelectElement | null)?.value
    const read = (name: string) => (form?.elements.namedItem(name) as HTMLInputElement | null)?.value.trim() || undefined
    setItems((rows) => rows.filter((row) => row.kind !== 'error'))
    void send(question, { year: year ? Number(year) : undefined, subject: read('subject'), topic: read('topic') }, true)
  }

  async function remove() {
    if (activeId === null) return
    setBusyDelete(true)
    try {
      await api<void>(`/conversations/${activeId}`, { method: 'DELETE' })
      setConversations((rows) => rows.filter((row) => row.id !== activeId))
      reset()
      setNotice('Conversación eliminada.')
    } catch (err) {
      setNotice(errorMessage(err))
    } finally {
      setBusyDelete(false)
      setConfirmDelete(false)
    }
  }

  async function loadMore() {
    try {
      const rows = await api<Conversation[]>(`/conversations?limit=${pageSize + 1}&offset=${conversations.length}`)
      setConversations((current) => [...current, ...rows.filter((row) => !current.some((c) => c.id === row.id)).slice(0, pageSize)])
      setMore(rows.length > pageSize)
    } catch (err) {
      setListError(errorMessage(err))
    }
  }

  const title = conversations.find((c) => c.id === activeId)?.title

  return (
    <>
      <h1>Consulta</h1>
      <div className="chat">
        <nav className="chat-list" aria-label="Conversaciones">
          <button type="button" className="secondary" disabled={busy} onClick={reset}>Nueva conversación</button>
          {listError && <p className="status error" role="alert">{listError}</p>}
          {conversations.length === 0 && !listError && <p className="note">Aún no tienes conversaciones.</p>}
          <ul>
            {conversations.map((c) => (
              <li key={c.id}>
                <button type="button" className="conversation" aria-current={c.id === activeId ? 'true' : undefined} disabled={busy} onClick={() => void open(c.id)}>
                  <span className="conversation-title">{c.title}</span>
                  <time dateTime={c.updated_at}>{date.format(new Date(c.updated_at))}</time>
                </button>
              </li>
            ))}
          </ul>
          {more && <button type="button" className="secondary small" disabled={busy} onClick={() => void loadMore()}>Ver más</button>}
        </nav>

        <section className="card chat-main" aria-label={title ? `Conversación: ${title}` : 'Conversación nueva'}>
          <div className="chat-head">
            <h2>{title ?? 'Conversación nueva'}</h2>
            {activeId !== null && <button type="button" className="secondary danger small" disabled={busy} onClick={() => setConfirmDelete(true)}>Borrar conversación</button>}
          </div>
          {notice && <p role="status" className="status">{notice}</p>}
          <div className="thread" role="log" aria-live="polite" aria-label="Mensajes" aria-busy={busy} tabIndex={0}>
            {items.length === 0 && !loading && <p className="empty">Pregunta lo que necesites sobre el corpus. Las preguntas de seguimiento usan el contexto de la conversación.</p>}
            {items.map((item) => <Bubble key={item.key} item={item} selected={selected?.key === item.key ? selected.position : null} onSelect={(position) => setSelected(position === null ? null : { key: item.key, position })} onRetry={retry} busy={busy} />)}
            {(thinking || loading) && <p className="bubble assistant loading" role="status">{loading ? 'Cargando la conversación…' : 'Pensando…'}</p>}
            <div ref={endRef} />
          </div>
          <form ref={formRef} className="composer" onSubmit={submit}>
            <details>
              <summary>Filtros del corpus (opcionales)</summary>
              <p className="note">Año, asignatura y tema acotan la búsqueda en el corpus; se aplican a cada pregunta que envíes.</p>
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
            </details>
            <label>
              Pregunta
              <textarea
                ref={inputRef} name="question" required maxLength={1000} rows={3}
                aria-describedby="chat-ayuda"
                onKeyDown={(event) => {
                  if (isSendKey(event.nativeEvent)) {
                    event.preventDefault()
                    formRef.current?.requestSubmit()
                  }
                }}
              />
            </label>
            <div className="actions">
              <button type="submit" disabled={busy}>Enviar</button>
              <p id="chat-ayuda" className="note">Enter envía; Shift+Enter hace un salto de línea.</p>
            </div>
          </form>
        </section>
      </div>

      <dialog ref={dialogRef} aria-labelledby="chat-borrar-titulo" aria-describedby="chat-borrar-texto" onClose={() => setConfirmDelete(false)}>
        <h2 id="chat-borrar-titulo">Borrar conversación</h2>
        <p id="chat-borrar-texto">Se borrarán «{title}» con todos sus mensajes y respuestas. Esta acción no se puede deshacer.</p>
        <div className="actions">
          <button type="button" className="secondary" autoFocus disabled={busyDelete} onClick={() => setConfirmDelete(false)}>Cancelar</button>
          <button type="button" disabled={busyDelete} onClick={() => void remove()}>{busyDelete ? 'Eliminando…' : 'Eliminar'}</button>
        </div>
      </dialog>
    </>
  )
}

function Bubble({ item, selected, onSelect, onRetry, busy }: {
  item: Item
  selected: number | null
  onSelect: (position: number | null) => void
  onRetry: (question: string) => void
  busy: boolean
}) {
  if (item.kind === 'pending') return <div className="bubble user"><p>{item.text}</p></div>
  if (item.kind === 'error') {
    return (
      <div className="bubble assistant error">
        <p className="status error" role="alert">{item.text}</p>
        <button type="button" className="secondary small" disabled={busy} onClick={() => onRetry(item.question)}>Reintentar</button>
      </div>
    )
  }
  const { message } = item
  if (message.role === 'user') return <div className="bubble user"><p>{message.content}</p></div>
  const answer = { content: message.content, citations: message.citations }
  return (
    <div className="bubble assistant">
      {message.status === 'no_evidence'
        ? <p className="status">{message.content || 'El corpus no contiene material que respalde una respuesta.'}</p>
        : <AnswerText answer={answer} onSelect={onSelect} />}
      {message.citations.length > 0 && <Citations citas={message.citations} selected={selected} onSelect={onSelect} level={3} />}
      {message.answer_id !== null && <Link className="feedback-link" to={`/feedback?answer_id=${message.answer_id}`}>Enviar feedback de esta respuesta</Link>}
    </div>
  )
}

/** Respuesta de consulta: una línea es un párrafo, «## Título» un encabezado y «- …» un elemento de lista. */
export function AnswerText({ answer, onSelect }: { answer: Pick<Answer, 'content' | 'citations'>; onSelect: (position: number) => void }) {
  const blocks: (string | string[])[] = []
  for (const line of answer.content.split('\n').map((row) => row.trim()).filter(Boolean)) {
    const last = blocks[blocks.length - 1]
    if (!line.startsWith('- ')) blocks.push(line)
    else if (Array.isArray(last)) last.push(line.slice(2))
    else blocks.push([line.slice(2)])
  }
  const marked = (text: string) => <MarkedText text={text} citas={answer.citations} onSelect={onSelect} />
  return blocks.map((block, i) => {
    if (Array.isArray(block)) return <ul key={i} className="outline">{block.map((item, j) => <li key={j}>{marked(item)}</li>)}</ul>
    if (block.startsWith('## ')) return <h3 key={i} className="answer-heading">{block.slice(3)}</h3>
    return <p key={i} className="answer">{marked(block)}</p>
  })
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

export function Citations({ citas, selected, onSelect, level = 2 }: { citas: Citation[]; selected: number | null; onSelect: (position: number | null) => void; level?: 2 | 3 }) {
  const open = citas.find((c) => c.position === selected)
  const id = useId()
  const Heading = level === 2 ? 'h2' : 'h3'
  return (
    <section aria-labelledby={`${id}-fuentes`}>
      <Heading id={`${id}-fuentes`}>Fuentes</Heading>
      <ol className="citations">
        {citas.map((cita) => (
          <li key={cita.position}>
            <button type="button" className="link" aria-expanded={cita === open} aria-controls={`${id}-visor`} onClick={() => onSelect(cita === open ? null : cita.position)}>
              <span className="cite-num">[{cita.position}]</span> <span className="cite-title">{cita.document_title},</span> <span className="cite-page">{pageName(cita)}</span>
            </button>
          </li>
        ))}
      </ol>
      {open && <CitationViewer key={open.position} id={`${id}-visor`} cita={open} />}
    </section>
  )
}

function CitationViewer({ cita, id }: { cita: Citation; id: string }) {
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
  const range = sameVersion ? citationRange(page.text, cita) : null
  const matches = !!range

  return (
    <div id={id} className="viewer">
      <h3 tabIndex={-1} ref={headingRef}>Cita [{cita.position}]</h3>
      <dl>
        <dt>Documento</dt><dd>{cita.document_title}</dd>
        <dt>Versión</dt><dd><code title={cita.document_version}>{cita.document_version.slice(0, 12)}</code></dd>
        <dt>Página</dt><dd>{cita.page_number}{cita.page_label && ` (impresa: ${cita.page_label})`}</dd>
      </dl>
      <blockquote className="source"><p>{cita.quote}</p></blockquote>
      {!page && (
        <button type="button" className="secondary" onClick={loadPage} disabled={state === 'loading'} aria-describedby={state === 'error' ? `${id}-error` : undefined}>
          Ver en la página
        </button>
      )}
      <p role="status" className="loading">{state === 'loading' ? 'Cargando la página…' : ''}</p>
      {state === 'error' && <p id={`${id}-error`} className="status error" role="alert">{error}</p>}
      {page && (
        <>
          {!sameVersion && <p className="status warning">El documento se ha actualizado desde esta cita; la página vigente puede no contener el texto citado.</p>}
          {sameVersion && !matches && <p className="status warning">El texto de la página no coincide con la cita guardada.</p>}
          {page.status === 'no_text' && <p className="note">La página no tiene texto extraíble.</p>}
          <div className="page" tabIndex={0} ref={pageRef} aria-label={`Texto de la página ${page.number}`}>
            {matches ? (
              <>
                {page.text.slice(0, range!.start)}
                <mark ref={markRef}>{cita.quote}</mark>
                {page.text.slice(range!.end)}
              </>
            ) : page.text}
          </div>
        </>
      )}
    </div>
  )
}
