import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api, ApiError, errorMessage, type Exam, type ExamAnswer, type FeedbackKind } from './api'
import { asignaturas } from './mock'

const difficultyLabels = { easy: 'Baja', medium: 'Media', hard: 'Alta' } as const

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
      <form onSubmit={generate}>
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
            <datalist id="exam-subjects">
              {asignaturas.map(({ nombre }) => <option key={nombre} value={nombre} />)}
            </datalist>
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
          <button type="submit">Generar examen</button>
        </fieldset>
      </form>

      <section aria-labelledby="saved-exams">
        <h2 id="saved-exams">Exámenes guardados</h2>
        {listStatus && <p role="status">{listStatus}</p>}
        {listError && <p role="alert" className="status error">{listError}</p>}
        {!listStatus && !listError && !exams.length && <p>Tu lista está vacía.</p>}
        {exams.length > 0 && (
          <ul>{exams.map((item) => (
            <li key={item.id}>
              <button type="button" disabled={pending} onClick={() => open(item)}>
                Examen {item.id} · {item.subject} · {difficultyLabels[item.difficulty]}
              </button>
            </li>
          ))}</ul>
        )}
      </section>

      {pending && <p role="status">Cargando…</p>}
      {error && <p role="alert" className="status error">{error}</p>}
      {exam && (
        <section className="result" aria-labelledby="active-exam">
          <h2 id="active-exam">{exam.subject}{exam.topic && ` · ${exam.topic}`}</h2>
          <form key={exam.id} onSubmit={reveal}>
            <ol>
              {exam.questions.map((question) => {
                const solution = answers.find((item) => item.question_id === question.id)
                return (
                  <li key={question.id}>
                    <label>{question.statement}<input name={String(question.id)} autoComplete="off" /></label>
                    {solution && (
                      <>
                        <p>Respuesta esperada: {solution.answer}</p>
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
            {answers.length === 0 && <button type="submit" disabled={pending}>Ver respuestas</button>}
          </form>
          <Link to={`/feedback?exam_id=${exam.id}`}>Enviar feedback de este examen</Link>
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
      {answerId && <p>Sobre la respuesta {answerId}</p>}
      {examId && <p>Sobre el examen {examId}</p>}
      <form onSubmit={submit}>
        <fieldset disabled={state === 'saving'}>
          <legend>Enviar feedback</legend>
          <label>Tipo
            <select value={kind} onChange={(event) => { setKind(event.target.value as FeedbackKind); setState('idle') }}>
              <option value="rating">Valoración</option>
              <option value="error">Reportar error</option>
              <option value="suggestion">Sugerir mejora</option>
            </select>
          </label>
          {kind === 'rating' && (
            <fieldset>
              <legend>Valoración</legend>
              {[1, 2, 3, 4, 5].map((value) => (
                <label key={value} className="choice">
                  <input type="radio" name="rating" value={value} required /> {value}
                </label>
              ))}
            </fieldset>
          )}
          <label>Comentario <textarea name="comment" rows={4} maxLength={2000} required={kind !== 'rating'} /></label>
          <button type="submit">{state === 'saving' ? 'Enviando…' : 'Enviar feedback'}</button>
        </fieldset>
      </form>
      {state === 'saved' && <p role="status">Tu feedback se guardó.</p>}
      {error && <p role="alert" className="status error">{error}</p>}
    </>
  )
}
