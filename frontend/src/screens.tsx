import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  api,
  ApiError,
  downloadPdf,
  errorMessage,
  questionKindLabels,
  type Exam,
  type ExamAnswer,
  type ExamKind,
  type FeedbackKind,
} from './api'
import { CorpusOptions } from './CorpusOptions'

const difficultyLabels = { easy: 'Baja', medium: 'Media', hard: 'Alta' } as const
const examKinds: ExamKind[] = ['multiple_choice', 'true_false', 'development', 'case']

export function Examen() {
  const [exams, setExams] = useState<Exam[]>([])
  const [exam, setExam] = useState<Exam | null>(null)
  const [answers, setAnswers] = useState<ExamAnswer[]>([])
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [listStatus, setListStatus] = useState('Cargando exámenes guardados…')
  const [listError, setListError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    api<Exam[]>('/exams', { signal: controller.signal })
      .then((rows) => {
        if (!controller.signal.aborted) {
          setExams((current) => [...current, ...rows.filter((row) => !current.some((item) => item.id === row.id))])
          setListStatus('')
          setListError('')
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setListStatus('')
          setListError(errorMessage(err))
        }
      })
    return () => controller.abort()
  }, [])

  function open(next: Exam) {
    setExam(next)
    setAnswers([])
    setError('')
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setPending(true)
    setError('')
    try {
      const created = await api<Exam>('/exams', {
        method: 'POST',
        body: JSON.stringify({
          year: Number(data.get('year')),
          subject: data.get('subject'),
          topic: String(data.get('topic') ?? '').trim() || undefined,
          difficulty: data.get('difficulty'),
          question_count: Number(data.get('question_count')),
          // Sin marcar ninguno (o los cuatro), el examen es mixto.
          types: data.getAll('types').length ? data.getAll('types') : undefined,
        }),
      })
      setExams((items) => [created, ...items.filter((item) => item.id !== created.id)])
      open(created)
    } catch (err) {
      setError(err instanceof ApiError && err.status === 422 ? err.message : errorMessage(err))
    } finally {
      setPending(false)
    }
  }

  async function save(path: string, filename: string) {
    setPending(true)
    setError('')
    try {
      await downloadPdf(path, filename)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPending(false)
    }
  }

  async function reveal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!exam) return
    setPending(true)
    setError('')
    try {
      setAnswers(await api<ExamAnswer[]>(`/exams/${exam.id}/answers`))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <>
      <h1>Examen</h1>
      <form className="card" onSubmit={generate}>
        <fieldset disabled={pending}>
          <legend>Configurar examen</legend>
          <div className="fields">
            <label>Año
              <select name="year">
                {[1, 2, 3, 4].map((year) => <option key={year} value={year}>{year}.º año</option>)}
              </select>
            </label>
            <label>Asignatura
              <input name="subject" list="exam-subjects" required maxLength={200} />
            </label>
            <CorpusOptions subjectsId="exam-subjects" />
            <label>Tema <input name="topic" maxLength={200} /></label>
            <label>Cantidad de preguntas
              <input name="question_count" type="number" min={1} max={50} defaultValue={2} required />
            </label>
            <label>Dificultad
              <select name="difficulty" defaultValue="medium">
                {Object.entries(difficultyLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </div>
          <fieldset className="kinds">
            <legend>Tipos de pregunta (sin marcar, mixto)</legend>
            {examKinds.map((kind) => (
              <label key={kind}><input type="checkbox" name="types" value={kind} /> {questionKindLabels[kind]}</label>
            ))}
          </fieldset>
          <button type="submit">Generar examen</button>
          {pending && <p role="status" className="loading">Generando el examen con la IA; puede tardar hasta un minuto…</p>}
        </fieldset>
      </form>

      <section aria-labelledby="saved-exams" className="card">
        <h2 id="saved-exams">Exámenes guardados</h2>
        {listStatus && <p role="status" className="loading">{listStatus}</p>}
        {listError && <p role="alert" className="status error">{listError}</p>}
        {!listStatus && !listError && !exams.length && <p className="empty">Tu lista está vacía.</p>}
        {exams.length > 0 && (
          <ul className="exam-list">{exams.map((item) => (
            <li key={item.id}>
              <button type="button" className="secondary" disabled={pending} onClick={() => open(item)} aria-current={item.id === exam?.id || undefined}>
                Examen {item.id} · {item.subject} · {difficultyLabels[item.difficulty]}
              </button>
            </li>
          ))}</ul>
        )}
      </section>

      {error && <p role="alert" className="status error">{error}</p>}
      {exam && (
        <section className="result" aria-labelledby="active-exam">
          <h2 id="active-exam">{exam.subject}{exam.topic && ` · ${exam.topic}`}</h2>
          <p className="note">{exam.duration_minutes} minutos · {String(exam.total_points).replace('.', ',')} puntos</p>
          <div className="actions">
            <button type="button" className="secondary" disabled={pending} onClick={() => save(`/exams/${exam.id}/pdf`, `examen-${exam.id}.pdf`)}>
              Descargar examen (PDF)
            </button>
            <button type="button" className="secondary" disabled={pending} onClick={() => save(`/exams/${exam.id}/answers/pdf`, `clave-examen-${exam.id}.pdf`)}>
              Descargar clave (PDF)
            </button>
          </div>
          <form key={exam.id} onSubmit={reveal}>
            <ol className="questions">
              {exam.questions.map((question) => {
                const solution = answers.find((item) => item.question_id === question.id)
                return (
                  <li key={question.id}>
                    <p><strong>{questionKindLabels[question.kind]}</strong> · {String(question.points).replace('.', ',')} pts</p>
                    <p className="statement">{question.statement}</p>
                    {question.kind === 'multiple_choice' && question.options?.map((option, index) => (
                      <label key={index}>
                        <input type="radio" name={String(question.id)} value={index} /> {'ABCD'[index]}) {option}
                      </label>
                    ))}
                    {question.kind === 'true_false' && ['Verdadero', 'Falso'].map((label) => (
                      <label key={label}><input type="radio" name={String(question.id)} value={label} /> {label}</label>
                    ))}
                    {question.kind !== 'multiple_choice' && (
                      <label>{question.kind === 'true_false' ? 'Justifica' : 'Respuesta'}
                        {question.kind === 'completion'
                          ? <input name={`${question.id}-text`} autoComplete="off" />
                          : <textarea name={`${question.id}-text`} rows={question.kind === 'case' ? 8 : 4} />}
                      </label>
                    )}
                    {solution && (
                      <>
                        <p className="solution">Respuesta esperada: {solution.answer}</p>
                        {solution.criteria && <p className="note">Criterio de corrección: {solution.criteria}</p>}
                        {solution.citations.map((citation) => (
                          <blockquote className="source" key={citation.position}>
                            <p>{citation.quote}</p>
                            <footer>{citation.document_title}, p. {citation.page_label ?? citation.page_number}</footer>
                          </blockquote>
                        ))}
                      </>
                    )}
                  </li>
                )
              })}
            </ol>
            <button type="submit" disabled={pending || answers.length > 0}>
              {answers.length > 0 ? 'Respuestas mostradas' : 'Ver respuestas'}
            </button>
            {answers.length > 0 && <p role="status" className="status ok">Respuestas y fuentes cargadas.</p>}
          </form>
          <Link className="feedback-link" to={`/feedback?exam_id=${exam.id}`}>Enviar feedback de este examen</Link>
        </section>
      )}
    </>
  )
}

export function Feedback() {
  const [params] = useSearchParams()
  const [kind, setKind] = useState<FeedbackKind>('rating')
  const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [error, setError] = useState('')
  const answerId = params.get('answer_id')
  const examId = params.get('exam_id')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setState('saving')
    setError('')
    try {
      await api('/feedback', {
        method: 'POST',
        body: JSON.stringify({
          kind,
          rating: kind === 'rating' ? Number(data.get('rating')) : undefined,
          comment: String(data.get('comment') ?? '').trim() || undefined,
          answer_id: answerId ?? undefined,
          exam_id: examId ?? undefined,
        }),
      })
      form.reset()
      setState('saved')
    } catch (err) {
      setError(errorMessage(err))
      setState('idle')
    }
  }

  return (
    <>
      <h1>Feedback</h1>
      {answerId && <p className="note">Sobre la respuesta {answerId}</p>}
      {examId && <p className="note">Sobre el examen {examId}</p>}
      <form className="card" onSubmit={submit}>
        <fieldset disabled={state === 'saving'} onChange={() => setState((s) => (s === 'saved' ? 'idle' : s))}>
          <legend>Enviar feedback</legend>
          <label>Tipo
            <select value={kind} onChange={(event) => { setKind(event.target.value as FeedbackKind); setState('idle') }}>
              <option value="rating">Valoración</option>
              <option value="error">Reportar error</option>
              <option value="suggestion">Sugerir mejora</option>
            </select>
          </label>
          {kind === 'rating' && (
            <fieldset className="options">
              <legend>Valoración</legend>
              {[1, 2, 3, 4, 5].map((value) => (
                <label key={value} className="choice">
                  <input type="radio" name="rating" value={value} required /> {value}
                </label>
              ))}
            </fieldset>
          )}
          <label>Comentario <textarea name="comment" rows={4} maxLength={2000} required={kind !== 'rating'} /></label>
          <button type="submit" disabled={state === 'saved'}>{state === 'saving' ? 'Enviando…' : 'Enviar feedback'}</button>
        </fieldset>
      </form>
      {state === 'saved' && <p role="status" className="status ok">Tu feedback se guardó.</p>}
      {error && <p role="alert" className="status error">{error}</p>}
    </>
  )
}
