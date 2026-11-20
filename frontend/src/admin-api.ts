// Tipos de /api/v1/admin (solo rol admin), alineados con el contrato del panel de administración.
import type { Answer, FeedbackKind, Role } from './api'

export interface AdminStats {
  users: { total: number; active: number; by_role: Record<Role, number> }
  documents: { total: number; active: number; retired: number; pages: number; pages_without_text: number }
  activity: {
    queries: number
    generations: number
    exams: number
    feedback: number
    no_evidence: number
    // 7 entradas, de hace 6 días a hoy (UTC), incluidas las de cero.
    last_7_days: { date: string; queries: number; generations: number; exams: number }[]
  }
}

export interface AdminUser {
  id: number
  email: string
  full_name: string
  role: Role
  is_active: boolean
  created_at: string
  active_sessions: number
}

export interface AdminUserCreate {
  email: string
  full_name: string
  role: Role
  password: string
}

export interface UserRef {
  id: number
  email: string
  full_name: string
}

export interface AdminAnswer {
  id: number
  kind: Answer['kind']
  status: Answer['status']
  question: string
  user: UserRef | null
  citations: number
  created_at: string
}

export interface AdminFeedback {
  id: number
  kind: FeedbackKind
  rating: number | null
  comment: string | null
  answer_id: number | null
  exam_id: number | null
  // null si la cuenta se borró.
  user: UserRef | null
  created_at: string
}

export type LogLevel = 'INFO' | 'WARNING' | 'ERROR'

/** Entrada tal como la emite app.logs; los campos de petición solo aparecen en los logs de acceso. */
export interface LogEntry {
  ts: string
  level: string
  logger: string
  message: string
  request_id?: string | null
  method?: string
  path?: string
  status?: number
  duration_ms?: number
  exception?: string
  [key: string]: unknown
}
