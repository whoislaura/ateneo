// Cliente y tipos de /api/v1, alineados con docs/api-contract.md y backend/app/schemas.py.

export type Role = 'student' | 'teacher' | 'admin'

export const roleLabels: Record<Role, string> = {
  student: 'Estudiante',
  teacher: 'Profesor',
  admin: 'Administrador',
}

export interface User {
  id: number
  email: string
  full_name: string
  role: Role
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export type QueryMode = 'breve' | 'desarrollada'

export interface QueryRequest {
  year?: number
  subject?: string
  topic?: string
  question: string
  /** Por defecto «breve»; la respuesta no lo devuelve. */
  mode?: QueryMode
}

export interface Citation {
  position: number
  chunk_id: string | null
  document_id: string
  document_title: string
  document_version: string
  page_number: number
  page_label: string | null
  start: number
  end: number
  quote: string
}

export interface Answer {
  id: number
  kind: 'query' | 'summary' | 'outline' | 'table' | 'diagram'
  status: 'answered' | 'no_evidence'
  question: string
  year: number | null
  subject: string | null
  topic: string | null
  content: string
  citations: Citation[]
  created_at: string
}

export interface Page {
  document_id: string
  version: string
  number: number
  label: string | null
  text: string
  status: 'text' | 'no_text'
}

export interface HistoryEntry {
  id: number
  action: 'query' | 'generation'
  summary: string
  created_at: string
}

// --- CU-03: corpus (AT-10, AT-23) ---

export type DocumentStatus = 'indexed' | 'partial' | 'retired'

export interface CorpusDocument {
  id: string
  title: string
  year: number
  subject: string
  topic: string
  filename: string
  version: string
  status: DocumentStatus
  created_at: string
  updated_at: string
}

export interface IngestionReport {
  document_id: string
  version: string
  status: 'indexed' | 'partial'
  pages: number
  chunks: number
  no_text_pages: number[]
  warnings: string[]
  chunk_settings: Record<string, number>
}

export const documentStatusLabels: Record<DocumentStatus, string> = {
  indexed: 'Indexado',
  partial: 'Indexado con páginas sin texto',
  retired: 'Retirado',
}

// --- fin CU-03 ---

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message)
  }
}

// El token vive en memoria y se copia en sessionStorage para sobrevivir a una recarga de la pestaña
// (se borra al cerrarla y no se comparte entre pestañas). Ver docs/frontend.md.
const TOKEN_KEY = 'ateneo.token'
let token: string | null = null
try {
  token = sessionStorage.getItem(TOKEN_KEY)
} catch {
  // Sin almacenamiento la sesión dura solo hasta recargar.
}

export function hasToken() {
  return token !== null
}

export function setToken(value: string | null) {
  token = value
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // Ídem.
  }
}

let onUnauthorized: () => void = () => {}
let onForbidden: () => void = () => {}

/** Se llama ante un 403 (el rol pudo cambiar en el servidor); el manejador revalida la sesión. */
export function setForbiddenHandler(handler: () => void) {
  onForbidden = handler
}

/** Se llama cuando una petición con token recibe 401 (sesión caducada o revocada). */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  // FormData (subida de PDFs) fija su propio Content-Type multipart con el boundary.
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const sentToken = token
  if (sentToken) headers.set('Authorization', `Bearer ${sentToken}`)

  const response = await fetch(`/api/v1${path}`, { ...init, headers })
  if (response.ok) return (response.status === 204 ? undefined : await response.json()) as T

  let code = 'http_error'
  let message = 'No se pudo completar la solicitud.'
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } }
    code = body.error?.code ?? code
    message = body.error?.message ?? message
  } catch {
    // Respuesta sin el formato de error del contrato (p. ej. proxy caído).
  }
  // Solo si el token sigue siendo el enviado: evita cerrar una sesión nueva por una respuesta tardía.
  if (response.status === 401 && sentToken && sentToken === token) {
    setToken(null)
    onUnauthorized()
  }
  // /auth/me queda fuera: el manejador lo llama y un 403 ahí provocaría un bucle.
  if (response.status === 403 && sentToken && path !== '/auth/me') onForbidden()
  throw new ApiError(response.status, code, message)
}

/** Descarga un PDF protegido (necesita el token, por eso no es un enlace) y lo guarda con `filename`. */
export async function downloadPdf(path: string, filename: string): Promise<void> {
  const headers = new Headers()
  const sentToken = token
  if (sentToken) headers.set('Authorization', `Bearer ${sentToken}`)
  const response = await fetch(`/api/v1${path}`, { headers })
  if (!response.ok) {
    if (response.status === 401 && sentToken && sentToken === token) {
      setToken(null)
      onUnauthorized()
    }
    if (response.status === 403 && sentToken) onForbidden()
    throw new ApiError(response.status, 'http_error', 'No se pudo descargar el PDF.')
  }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/** Mensaje para el usuario según el error de `api()` (compartido por las pantallas). */
export function errorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return 'No se pudo conectar con el servidor. Comprueba la conexión e inténtalo de nuevo.'
  if (err.status === 401) return 'Tu sesión ha caducado.'
  if (err.status === 403) return 'Tu rol no tiene permiso para esta acción.'
  if (err.status === 404) return 'El recurso solicitado no existe o ya no está disponible.'
  if (err.status === 422) return 'Revisa los datos: hay campos no válidos.'
  // Sin cuerpo JSON del contrato (code por defecto): lo respondió el proxy mientras la API arranca o tarda.
  if ([502, 503, 504].includes(err.status) && err.code === 'http_error') return 'El servidor tardó demasiado o se está iniciando; inténtalo de nuevo en un minuto.'
  if (err.status === 501) return 'Esta función aún no está disponible en el servidor.'
  return err.message
}

// CU-02 (AT-22): generación de material. La estructura de `content` por formato está en docs/api-contract.md.

export type GenerationFormat = 'summary' | 'outline' | 'table' | 'diagram'

export const formatLabels: Record<GenerationFormat, string> = {
  summary: 'Resumen',
  outline: 'Esquema',
  table: 'Cuadro comparativo',
  diagram: 'Diagrama de texto',
}

export interface GenerationRequest {
  format: GenerationFormat
  prompt: string
  year?: number
  subject?: string
  topic?: string
}

export type Difficulty = 'easy' | 'medium' | 'hard'

export type QuestionKind = 'multiple_choice' | 'true_false' | 'development' | 'case' | 'completion'
/** Tipos que el profesor puede elegir al generar; «completion» solo existe en exámenes antiguos. */
export type ExamKind = Exclude<QuestionKind, 'completion'>

export const questionKindLabels: Record<QuestionKind, string> = {
  multiple_choice: 'Test',
  true_false: 'Verdadero o falso',
  development: 'Desarrollo',
  case: 'Caso práctico',
  completion: 'Completar',
}

export interface ExamQuestion {
  id: number
  position: number
  kind: QuestionKind
  statement: string
  options: string[] | null
  points: number
}

export interface Exam {
  id: number
  year: number
  subject: string
  topic: string | null
  difficulty: Difficulty
  question_count: number
  duration_minutes: number
  total_points: number
  questions: ExamQuestion[]
  created_at: string
}

export interface ExamAnswer {
  question_id: number
  position: number
  answer: string
  criteria: string | null
  citations: Citation[]
}

export type FeedbackKind = 'rating' | 'error' | 'suggestion'
