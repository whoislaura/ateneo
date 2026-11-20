import { useEffect, useState } from 'react'
import { api, type CorpusDocument } from './api'

export function CorpusOptions({ subjectsId, topicsId, subject = '' }: {
  subjectsId: string
  topicsId?: string
  subject?: string
}) {
  const [documents, setDocuments] = useState<CorpusDocument[]>([])
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    api<CorpusDocument[]>('/documents', { signal: controller.signal }).then(
      (rows) => { if (!controller.signal.aborted) setDocuments(rows) },
      () => { if (!controller.signal.aborted) setFailed(true) },
    )
    return () => controller.abort()
  }, [])

  const subjects = [...new Set(documents.map((doc) => doc.subject))].sort((a, b) => a.localeCompare(b, 'es'))
  const key = (text: string) => text.trim().normalize('NFC').toLocaleLowerCase('es')
  const topics = [...new Set(documents.filter((doc) => !subject.trim() || key(doc.subject) === key(subject)).map((doc) => doc.topic))].sort((a, b) => a.localeCompare(b, 'es'))

  return <>
    <datalist id={subjectsId}>{subjects.map((name) => <option key={name} value={name} />)}</datalist>
    {topicsId && <datalist id={topicsId}>{topics.map((name) => <option key={name} value={name} />)}</datalist>}
    {failed && <p role="status" className="note">No se pudieron cargar las sugerencias del corpus. Puedes escribir la asignatura y el tema.</p>}
  </>
}
