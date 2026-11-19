// Datos ficticios para las pantallas aún no integradas (AT-05). Los tipos de la API están en api.ts.
import type { Citation } from './api'

export interface Asignatura {
  anio: number
  nombre: string
  temas: string[]
}


export interface HistoryEntry {
  id: string
  fecha: string
  accion: 'consulta' | 'generación' | 'examen'
  resumen: string
}

export interface ExamQuestion {
  id: string
  enunciado: string
  opciones: string[]
  correcta: number
  cita: Citation
}

export const asignaturas: Asignatura[] = [
  { anio: 1, nombre: 'Derecho Romano', temas: ['Fuentes del Derecho Romano', 'Personas', 'Obligaciones'] },
  { anio: 1, nombre: 'Teoría del Estado', temas: ['El Estado', 'Formas de gobierno'] },
  { anio: 2, nombre: 'Derecho Constitucional', temas: ['La Constitución', 'Derechos fundamentales'] },
  { anio: 3, nombre: 'Derecho Penal', temas: ['El delito', 'La pena'] },
  { anio: 4, nombre: 'Derecho Mercantil', temas: ['El empresario', 'Sociedades mercantiles'] },
]

const manual = 'Manual de Derecho Romano (muestra)'

function cita(position: number, page: number, quote: string): Citation {
  return {
    position, chunk_id: null, document_id: 'muestra-manual', document_title: manual,
    document_version: 'muestra', page_number: page, page_label: null, start: 0, end: quote.length, quote,
  }
}

const sampleCitations: Citation[] = [
  cita(1, 12, 'Son fuentes del derecho la costumbre, la ley, el plebiscito, el senadoconsulto, el edicto y la respuesta de los prudentes…'),
  cita(2, 15, 'Durante el Principado, la voluntad del príncipe expresada en constituciones adquiere fuerza de ley…'),
]


export const history: HistoryEntry[] = [
  { id: 'h-1', fecha: '2026-11-18 10:42', accion: 'consulta', resumen: '¿Cuáles son las fuentes del Derecho Romano?' },
  { id: 'h-2', fecha: '2026-11-18 11:05', accion: 'generación', resumen: 'Esquema: Fuentes del Derecho Romano' },
  { id: 'h-3', fecha: '2026-11-17 16:20', accion: 'examen', resumen: 'Derecho Romano · 2 preguntas · 1/2 correctas' },
]

export const exam: ExamQuestion[] = [
  {
    id: 'q-1',
    enunciado: '¿Qué órgano dictaba los senadoconsultos?',
    opciones: ['Los comicios', 'El Senado', 'El pretor'],
    correcta: 1,
    cita: cita(1, 13, 'El senadoconsulto es lo que el Senado manda y establece…'),
  },
  {
    id: 'q-2',
    enunciado: '¿Qué fuente gana peso durante el Principado?',
    opciones: ['La costumbre', 'Los plebiscitos', 'Las constituciones imperiales'],
    correcta: 2,
    cita: sampleCitations[1],
  },
]
