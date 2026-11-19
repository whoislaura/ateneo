// Datos ficticios para las pantallas aún no integradas (AT-05). Los tipos de la API están en api.ts.
import type { Citation } from './api'

export interface Asignatura {
  anio: number
  nombre: string
  temas: string[]
}

export type GenerationType = 'resumen' | 'esquema' | 'cuadro' | 'diagrama'

export interface CorpusDocument {
  id: string
  titulo: string
  anio: number
  asignatura: string
  tema: string
  paginas: number
  estado: 'procesado' | 'pendiente' | 'retirado'
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

export const sampleCitations: Citation[] = [
  cita(1, 12, 'Son fuentes del derecho la costumbre, la ley, el plebiscito, el senadoconsulto, el edicto y la respuesta de los prudentes…'),
  cita(2, 15, 'Durante el Principado, la voluntad del príncipe expresada en constituciones adquiere fuerza de ley…'),
]

export const sampleGenerations: Record<GenerationType, string> = {
  resumen: 'Las fuentes del Derecho Romano evolucionan de la costumbre a la ley escrita y, más tarde, a las constituciones imperiales.',
  esquema: '1. Fuentes\n   1.1 Costumbre\n   1.2 Leyes y plebiscitos\n   1.3 Senadoconsultos\n   1.4 Edictos\n   1.5 Jurisprudencia\n2. Constituciones imperiales',
  cuadro: 'Fuente            | Órgano             | Época\n------------------|--------------------|-----------\nLey               | Comicios           | República\nSenadoconsulto    | Senado             | República\nConstitución      | Emperador          | Principado',
  diagrama: 'Costumbre → Ley escrita → Edictos → Constituciones imperiales',
}

export const corpus: CorpusDocument[] = [
  { id: 'doc-1', titulo: manual, anio: 1, asignatura: 'Derecho Romano', tema: 'Fuentes del Derecho Romano', paginas: 42, estado: 'procesado' },
  { id: 'doc-2', titulo: 'Lecturas de Teoría del Estado (muestra)', anio: 1, asignatura: 'Teoría del Estado', tema: 'El Estado', paginas: 30, estado: 'pendiente' },
  { id: 'doc-3', titulo: 'Apuntes de Derecho Penal (muestra)', anio: 3, asignatura: 'Derecho Penal', tema: 'El delito', paginas: 25, estado: 'retirado' },
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
