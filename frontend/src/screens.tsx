import { useState, type FormEvent } from 'react'
import { Citations } from './consulta'
import { asignaturas, corpus, exam, history, sampleCitations, sampleGenerations, type GenerationType } from './mock'

const MOCK_NOTE = 'Pantalla de demostración: los resultados son ficticios.'

function SubjectFields() {
  const [anio, setAnio] = useState(1)
  const [nombre, setNombre] = useState(asignaturas[0].nombre)
  const delAnio = asignaturas.filter((a) => a.anio === anio)
  const asignatura = delAnio.find((a) => a.nombre === nombre) ?? delAnio[0]

  return (
    <div className="fields">
      <label>
        Año
        <select value={anio} onChange={(e) => { const value = Number(e.target.value); setAnio(value); setNombre(asignaturas.find((a) => a.anio === value)!.nombre) }}>
          {[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value}.º año</option>)}
        </select>
      </label>
      <label>
        Asignatura
        <select value={asignatura.nombre} onChange={(e) => setNombre(e.target.value)}>
          {delAnio.map((a) => <option key={a.nombre}>{a.nombre}</option>)}
        </select>
      </label>
      <label>
        Tema
        <select>
          {asignatura.temas.map((tema) => <option key={tema}>{tema}</option>)}
        </select>
      </label>
    </div>
  )
}

function useSubmitted() {
  const [submitted, setSubmitted] = useState(false)
  return [submitted, (event: FormEvent) => { event.preventDefault(); setSubmitted(true) }] as const
}

export function Generacion() {
  const [tipo, setTipo] = useState<GenerationType>('resumen')
  const [selected, setSelected] = useState<number | null>(null)
  const [submitted, submit] = useSubmitted()
  return (
    <>
      <h1>Generación de material</h1>
      <form onSubmit={submit}>
        <SubjectFields />
        <label>
          Tipo
          <select value={tipo} onChange={(e) => setTipo(e.target.value as GenerationType)}>
            <option value="resumen">Resumen</option>
            <option value="esquema">Esquema</option>
            <option value="cuadro">Cuadro</option>
            <option value="diagrama">Diagrama de texto</option>
          </select>
        </label>
        <button type="submit">Generar</button>
      </form>
      {submitted && (
        <section aria-labelledby="generado" className="result">
          <h2 id="generado">Resultado</h2>
          <p className="note">{MOCK_NOTE}</p>
          <pre>{sampleGenerations[tipo]}</pre>
          <Citations citas={sampleCitations} selected={selected} onSelect={setSelected} />
        </section>
      )}
    </>
  )
}

export function Corpus() {
  const [submitted, submit] = useSubmitted()
  return (
    <>
      <h1>Gestión de corpus</h1>
      <form onSubmit={submit}>
        <SubjectFields />
        <label>
          Documento PDF
          <input type="file" accept="application/pdf" />
        </label>
        <button type="submit">Subir material</button>
        {submitted && <p role="status">Subida simulada: no se envió ningún archivo.</p>}
      </form>
      <table>
        <caption>Material registrado</caption>
        <thead>
          <tr><th scope="col">Título</th><th scope="col">Año</th><th scope="col">Asignatura</th><th scope="col">Tema</th><th scope="col">Páginas</th><th scope="col">Estado</th><th scope="col">Acciones</th></tr>
        </thead>
        <tbody>
          {corpus.map((doc) => (
            <tr key={doc.id}>
              <td>{doc.titulo}</td><td>{doc.anio}.º</td><td>{doc.asignatura}</td><td>{doc.tema}</td><td>{doc.paginas}</td><td>{doc.estado}</td>
              <td>
                <button type="button" disabled aria-label={`Actualizar ${doc.titulo}`}>Actualizar</button>{' '}
                <button type="button" disabled aria-label={`Retirar ${doc.titulo}`}>Retirar</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

export function Historial() {
  return (
    <>
      <h1>Historial</h1>
      <table>
        <caption>Actividad reciente</caption>
        <thead>
          <tr><th scope="col">Fecha</th><th scope="col">Acción</th><th scope="col">Resumen</th></tr>
        </thead>
        <tbody>
          {history.map((entry) => (
            <tr key={entry.id}><td>{entry.fecha}</td><td>{entry.accion}</td><td>{entry.resumen}</td></tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

export function Examen() {
  const [started, start] = useSubmitted()
  const [corrected, correct] = useSubmitted()
  const [answers, setAnswers] = useState<Record<string, number>>({})

  return (
    <>
      <h1>Examen</h1>
      <form onSubmit={start}>
        <SubjectFields />
        <div className="fields">
          <label>
            Cantidad de preguntas
            <input type="number" min={1} max={20} defaultValue={exam.length} />
          </label>
          <label>
            Dificultad
            <select defaultValue="media">
              <option value="baja">Baja</option>
              <option value="media">Media</option>
              <option value="alta">Alta</option>
            </select>
          </label>
        </div>
        <button type="submit">Generar examen</button>
      </form>
      {started && (
        <form onSubmit={correct} className="result">
          <p className="note">{MOCK_NOTE}</p>
          {exam.map((question, index) => (
            <fieldset key={question.id}>
              <legend>{index + 1}. {question.enunciado}</legend>
              {question.opciones.map((option, i) => (
                <label key={option} className="choice">
                  <input type="radio" name={question.id} required checked={answers[question.id] === i} onChange={() => setAnswers({ ...answers, [question.id]: i })} />
                  {option}
                </label>
              ))}
              {corrected && (
                <p>
                  {answers[question.id] === question.correcta ? 'Correcta.' : `Incorrecta. Respuesta: ${question.opciones[question.correcta]}.`}{' '}
                  Fuente: [{question.cita.document_title}, p. {question.cita.page_number}]
                </p>
              )}
            </fieldset>
          ))}
          <button type="submit">Ver respuestas</button>
        </form>
      )}
    </>
  )
}

export function Feedback() {
  const [submitted, submit] = useSubmitted()
  return (
    <>
      <h1>Feedback</h1>
      <form onSubmit={submit}>
        <fieldset>
          <legend>Valoración de la última respuesta</legend>
          {[1, 2, 3, 4, 5].map((value) => (
            <label key={value} className="choice">
              <input type="radio" name="valoracion" value={value} required /> {value}
            </label>
          ))}
        </fieldset>
        <label>
          Tipo
          <select defaultValue="error">
            <option value="error">Reportar error</option>
            <option value="sugerencia">Sugerir mejora</option>
          </select>
        </label>
        <label>
          Comentario
          <textarea rows={4} />
        </label>
        <button type="submit">Enviar</button>
        {submitted && <p role="status">Gracias. Envío simulado: no se guardó nada.</p>}
      </form>
    </>
  )
}
