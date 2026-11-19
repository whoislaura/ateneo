// Datos ficticios para las pantallas aún no integradas (AT-05). Los tipos de la API están en api.ts.

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

export const asignaturas: Asignatura[] = [
  { anio: 1, nombre: 'Derecho Romano', temas: ['Fuentes del Derecho Romano', 'Personas', 'Obligaciones'] },
  { anio: 1, nombre: 'Teoría del Estado', temas: ['El Estado', 'Formas de gobierno'] },
  { anio: 2, nombre: 'Derecho Constitucional', temas: ['La Constitución', 'Derechos fundamentales'] },
  { anio: 3, nombre: 'Derecho Penal', temas: ['El delito', 'La pena'] },
  { anio: 4, nombre: 'Derecho Mercantil', temas: ['El empresario', 'Sociedades mercantiles'] },
]

export const history: HistoryEntry[] = [
  { id: 'h-1', fecha: '2026-11-18 10:42', accion: 'consulta', resumen: '¿Cuáles son las fuentes del Derecho Romano?' },
  { id: 'h-2', fecha: '2026-11-18 11:05', accion: 'generación', resumen: 'Esquema: Fuentes del Derecho Romano' },
  { id: 'h-3', fecha: '2026-11-17 16:20', accion: 'examen', resumen: 'Derecho Romano · 2 preguntas · 1/2 correctas' },
]
