import type { Citation } from './api'

/** Ruta pedida (`from`) solo si su pantalla está permitida; si no, la raíz. */
export function intendedPath(from: string | undefined, allowedPaths: string[]): string {
  const first = from?.split(/[?#]/)[0].split('/')[1]
  return from && first && allowedPaths.includes(first) ? from : '/'
}

/**
 * Rango UTF-16 de la cita en `text`. Los offsets del backend son code points de Python,
 * no unidades UTF-16 de `String.slice`; si no coinciden se busca la cita literal.
 */
export function citationRange(text: string, cita: Pick<Citation, 'start' | 'end' | 'quote'>): { start: number; end: number } | null {
  const points = Array.from(text)
  if (points.slice(cita.start, cita.end).join('') === cita.quote) {
    const start = points.slice(0, cita.start).join('').length
    return { start, end: start + cita.quote.length }
  }
  const start = text.indexOf(cita.quote)
  return cita.quote && start >= 0 ? { start, end: start + cita.quote.length } : null
}

/** Enter envía el mensaje; Shift+Enter (o una composición de IME en curso) inserta un salto de línea. */
export function isSendKey(event: { key: string; shiftKey: boolean; isComposing: boolean }): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing
}
