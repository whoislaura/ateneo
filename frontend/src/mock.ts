// Sugerencias ficticias de asignatura y tema (AT-05). Los tipos de la API están en api.ts.

export interface Asignatura {
  anio: number
  nombre: string
  temas: string[]
}

export const asignaturas: Asignatura[] = [
  { anio: 1, nombre: 'Derecho Romano', temas: ['Fuentes del Derecho Romano', 'Personas', 'Obligaciones'] },
  { anio: 1, nombre: 'Teoría del Estado', temas: ['El Estado', 'Formas de gobierno'] },
  { anio: 2, nombre: 'Derecho Constitucional', temas: ['La Constitución', 'Derechos fundamentales'] },
  { anio: 3, nombre: 'Derecho Penal', temas: ['El delito', 'La pena'] },
  { anio: 4, nombre: 'Derecho Mercantil', temas: ['El empresario', 'Sociedades mercantiles'] },
]
