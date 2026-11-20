import { ApiError, errorMessage, formatLabels, type Answer } from '../api'

export const pageSize = 20
export const dateTime = new Intl.DateTimeFormat('es-CU', { dateStyle: 'short', timeStyle: 'short' })
export const kindLabels: Record<Answer['kind'], string> = { query: 'Consulta', ...formatLabels }
export const answerStatusLabels: Record<Answer['status'], string> = { answered: 'Respondida', no_evidence: 'Sin evidencia' }
export const feedbackLabels = { rating: 'Valoración', error: 'Error', suggestion: 'Sugerencia' } as const

/** 409 y 422 traen un mensaje concreto de la API (email repetido, último admin, contraseña corta…). */
export function actionError(err: unknown): string {
  return err instanceof ApiError && (err.status === 409 || err.status === 422) ? err.message : errorMessage(err)
}
