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

export interface QueryRequest {
  year?: number
  subject?: string
  topic?: string
  question: string
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

/** Se llama cuando una petición con token recibe 401 (sesión caducada o revocada). */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
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
  throw new ApiError(response.status, code, message)
}

/** Mensaje para el usuario según el error de `api()` (compartido por las pantallas). */
export function errorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return 'No se pudo conectar con el servidor. Comprueba la conexión e inténtalo de nuevo.'
  if (err.status === 401) return 'Tu sesión ha caducado.'
  if (err.status === 403) return 'Tu rol no tiene permiso para esta acción.'
  if (err.status === 404) return 'El recurso solicitado no existe o ya no está disponible.'
  if (err.status === 422) return 'Revisa los datos: hay campos no válidos.'
  if (err.status === 501) return 'Esta función aún no está disponible en el servidor.'
  return err.message
}

// CU-02 (AT-22): generación de material. La estructura de `content` por formato está en docs/api-contract.md.

export type GenerationFormat = 'summary' | 'outline' | 'table' | 'diagram'

export interface GenerationRequest {
  format: GenerationFormat
  prompt: string
  year?: number
  subject?: string
  topic?: string
}
