import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type CorpusDocument, type DocumentStatus, type IngestionReport } from './api'

const statusLabels: Record<DocumentStatus, string> = {
  indexed: 'Indexado',
  partial: 'Indexado con páginas sin texto',
  retired: 'Retirado',
}

interface Filters {
  year: string
  subject: string
  topic: string
  includeRetired: boolean
}

interface Confirmation {
  kind: 'replace' | 'retire'
  doc: CorpusDocument
  data?: FormData
}

// Los mensajes de la API (409, 413, 422 de extracción, 503) ya están en español para el usuario.
function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return 'No se pudo conectar con el servidor. Comprueba la conexión e inténtalo de nuevo.'
  if (err.status === 403) return 'Tu rol no tiene permiso para esta acción.'
  if (err.status === 404) return 'El documento no existe o ya no está disponible.'
  return err.message
}

const documentPath = (id: string) => `/documents/${encodeURIComponent(id)}`

function reportText(title: string, report: IngestionReport): string {
  const missing = report.no_text_pages.length
    ? ` Páginas sin texto extraíble: ${report.no_text_pages.join(', ')}; revisa si están vacías o requieren OCR.`
    : ''
  return `«${title}» indexado: ${report.pages} páginas, ${report.chunks} fragmentos.${missing}`
}

export function Corpus() {
  const [filters, setFilters] = useState<Filters>({ year: '', subject: '', topic: '', includeRetired: false })
  const [reload, setReload] = useState(0)
  const [docs, setDocs] = useState<CorpusDocument[] | null>(null)
  const [listError, setListError] = useState('')
  const [editing, setEditing] = useState<CorpusDocument | null>(null)
  const [formKey, setFormKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [retiring, setRetiring] = useState<string | null>(null)
  const [formError, setFormError] = useState('')
  const [notice, setNotice] = useState('')
  const [confirm, setConfirm] = useState<Confirmation | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const errorRef = useRef<HTMLParagraphElement>(null)
  const noticeRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    const params = new URLSearchParams()
    if (filters.year) params.set('year', filters.year)
    if (filters.subject) params.set('subject', filters.subject)
    if (filters.topic) params.set('topic', filters.topic)
    if (filters.includeRetired) params.set('include_retired', 'true')
    let active = true
    api<CorpusDocument[]>(`/documents?${params}`).then(
      (result) => {
        if (!active) return
        setDocs(result)
        setListError('')
      },
      (err) => active && setListError(errorText(err)),
    )
    return () => {
      active = false
    }
  }, [filters, reload])

  // El diálogo nativo modal atrapa el foco, se cierra con Escape y devuelve el foco al botón que lo abrió.
  useEffect(() => {
    const dialog = dialogRef.current
    if (confirm && !dialog?.open) dialog?.showModal()
    if (!confirm && dialog?.open) dialog.close()
  }, [confirm])

  useEffect(() => {
    if (editing) headingRef.current?.focus()
  }, [editing])

  useEffect(() => {
    if (formError) errorRef.current?.focus()
  }, [formError])

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const text = (name: string) => String(data.get(name) ?? '').trim()
    setFilters({ year: text('year'), subject: text('subject'), topic: text('topic'), includeRetired: data.has('include_retired') })
  }

  function startEditing(doc: CorpusDocument) {
    setEditing(doc)
    setFormError('')
    setNotice('')
  }

  function stopEditing() {
    setEditing(null)
    setFormError('')
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    if (editing) setConfirm({ kind: 'replace', doc: editing, data })
    else void send(data, () => api<IngestionReport>('/documents', { method: 'POST', body: data }))
  }

  async function send(data: FormData, request: () => Promise<IngestionReport>) {
    setBusy(true)
    setFormError('')
    setNotice('')
    try {
      const report = await request()
      setNotice(reportText(String(data.get('title')), report))
      setEditing(null)
      setFormKey((key) => key + 1)
      setReload((n) => n + 1)
    } catch (err) {
      setFormError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function retire(doc: CorpusDocument) {
    setRetiring(doc.id)
    setNotice('')
    setListError('')
    setFormError('')
    try {
      await api<void>(documentPath(doc.id), { method: 'DELETE' })
      setNotice(`«${doc.title}» retirado: ya no se usa en respuestas nuevas.`)
      if (editing?.id === doc.id) setEditing(null)
      setReload((n) => n + 1)
      // La fila (y su botón) puede desaparecer de la lista: el foco pasa al aviso.
      noticeRef.current?.focus()
    } catch (err) {
      setListError(errorText(err))
    } finally {
      setRetiring(null)
    }
  }

  function accept() {
    if (!confirm) return
    const { kind, doc, data } = confirm
    setConfirm(null)
    if (kind === 'retire') void retire(doc)
    else if (data) void send(data, () => api<IngestionReport>(documentPath(doc.id), { method: 'PUT', body: data }))
  }

  const fileHelp = ['corpus-file-help', formError && 'corpus-form-error'].filter(Boolean).join(' ')

  return (
    <>
      <h1>Gestión de corpus</h1>

      <section aria-labelledby="corpus-form-title" className="card">
        <h2 id="corpus-form-title" tabIndex={-1} ref={headingRef}>
          {editing ? `Actualizar «${editing.title}»` : 'Subir material'}
        </h2>
        <form key={`${editing?.id ?? 'nuevo'}-${formKey}`} onSubmit={submit} aria-busy={busy}>
          {editing && (
            <p className="note">
              Identificador <code>{editing.id}</code>. El nuevo PDF sustituye la versión vigente y se reindexa; las citas ya guardadas conservan su copia.
            </p>
          )}
          <fieldset className="plain" disabled={busy}>
            {!editing && (
              <label>
                Identificador
                <input
                  name="document_id" required maxLength={200} pattern="[A-Za-z0-9][A-Za-z0-9._\-]*"
                  aria-describedby="corpus-id-help"
                />
              </label>
            )}
            {!editing && (
              <p id="corpus-id-help" className="note">Único y estable: letras sin tilde, números, punto, guion o guion bajo. No se puede cambiar después.</p>
            )}
            <label>
              Título
              <input name="title" required maxLength={200} defaultValue={editing?.title} />
            </label>
            <div className="fields">
              <label>
                Año
                <select name="year" required defaultValue={editing?.year ?? 1}>
                  {[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value}.º año</option>)}
                </select>
              </label>
              <label>
                Asignatura
                <input name="subject" required maxLength={200} defaultValue={editing?.subject} />
              </label>
              <label>
                Tema
                <input name="topic" required maxLength={200} defaultValue={editing?.topic} />
              </label>
            </div>
            <label>
              Documento PDF
              <input name="file" type="file" required accept="application/pdf,.pdf" aria-describedby={fileHelp} />
            </label>
            <p id="corpus-file-help" className="note">PDF con texto seleccionable; no se aplica OCR a páginas escaneadas.</p>
          </fieldset>
          <div className="actions">
            <button type="submit" disabled={busy}>
              {busy ? 'Procesando…' : editing ? 'Actualizar material' : 'Subir material'}
            </button>
            {editing && <button type="button" className="secondary" onClick={stopEditing} disabled={busy}>Cancelar</button>}
          </div>
          {busy && <progress aria-label="Procesando el PDF" />}
          <p role="status" className="note">{busy ? 'Subiendo, extrayendo e indexando el PDF; puede tardar unos segundos.' : ''}</p>
          {formError && (
            <p id="corpus-form-error" className="status error" role="alert" tabIndex={-1} ref={errorRef}>{formError}</p>
          )}
        </form>
      </section>

      <p role="status" className={notice ? 'status ok' : undefined} tabIndex={-1} ref={noticeRef}>{notice}</p>

      <section aria-labelledby="corpus-list-title" className="card">
        <h2 id="corpus-list-title">Material registrado</h2>
        <form onSubmit={filter} aria-label="Filtrar material">
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
              <input name="subject" maxLength={200} />
            </label>
            <label>
              Tema
              <input name="topic" maxLength={200} />
            </label>
          </div>
          <label className="choice">
            <input type="checkbox" name="include_retired" /> Incluir retirados
          </label>
          <button type="submit" className="secondary">Filtrar</button>
        </form>

        {listError && (
          <>
            <p className="status error" role="alert">{listError}</p>
            <button type="button" className="secondary" onClick={() => { setDocs(null); setListError(''); setReload((n) => n + 1) }}>Reintentar</button>
          </>
        )}
        {docs === null && !listError && <p role="status" className="loading">Cargando el corpus…</p>}
        {docs?.length === 0 && <p className="empty">No hay material con estos filtros.</p>}
        {docs && docs.length > 0 && (
          <div className="table-wrap" role="region" aria-label="Documentos" tabIndex={0}>
            <table>
              <caption>Documentos ({docs.length})</caption>
              <thead>
                <tr>
                  <th scope="col">Título</th><th scope="col">Identificador</th><th scope="col">Año</th><th scope="col">Asignatura</th>
                  <th scope="col">Tema</th><th scope="col">Archivo</th><th scope="col">Estado</th><th scope="col">Actualizado</th><th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((doc) => (
                  <tr key={doc.id}>
                    <td>{doc.title}</td><td><code>{doc.id}</code></td><td>{doc.year}.º</td><td>{doc.subject}</td><td>{doc.topic}</td>
                    <td>{doc.filename}</td><td><span className={`badge ${doc.status}`}>{statusLabels[doc.status]}</span></td>
                    <td><time dateTime={doc.updated_at}>{new Date(doc.updated_at).toLocaleDateString('es')}</time></td>
                    <td>
                      <div className="actions">
                        <button type="button" className="secondary small" disabled={busy} onClick={() => startEditing(doc)} aria-label={`Actualizar ${doc.title}`}>
                          Actualizar
                        </button>
                        {doc.status !== 'retired' && (
                          <button
                            type="button" className="secondary danger small" disabled={retiring === doc.id}
                            onClick={() => setConfirm({ kind: 'retire', doc })} aria-label={`Retirar ${doc.title}`}
                          >
                            {retiring === doc.id ? 'Retirando…' : 'Retirar'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <dialog ref={dialogRef} aria-labelledby="corpus-confirm-title" aria-describedby="corpus-confirm-text" onClose={() => setConfirm(null)}>
        {confirm && (
          <>
            <h2 id="corpus-confirm-title">{confirm.kind === 'retire' ? 'Retirar material' : 'Sustituir material'}</h2>
            <p id="corpus-confirm-text">
              {confirm.kind === 'retire'
                ? `«${confirm.doc.title}» dejará de usarse en consultas y citas nuevas. Se conserva para el historial y se puede reactivar subiendo una nueva versión.`
                : `El PDF y los datos de «${confirm.doc.title}» se sustituirán y se reindexará el documento. Las citas ya guardadas conservan su copia.`}
            </p>
            <div className="actions">
              <button type="button" className="secondary" autoFocus onClick={() => setConfirm(null)}>Cancelar</button>
              <button type="button" className={confirm.kind === 'retire' ? 'danger' : undefined} onClick={accept}>{confirm.kind === 'retire' ? 'Retirar' : 'Sustituir'}</button>
            </div>
          </>
        )}
      </dialog>
    </>
  )
}
