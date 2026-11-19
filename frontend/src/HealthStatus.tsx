import { useEffect, useState } from 'react'

export default function HealthStatus() {
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 10_000)
    let active = true
    async function checkConnection() {
      try {
        const response = await fetch('/api/v1/health', { signal: controller.signal })
        if (!response.ok) throw new Error('API unavailable')
        const body: unknown = await response.json()
        if (!body || typeof body !== 'object' || !('status' in body) || body.status !== 'ok') {
          throw new Error('Unexpected response')
        }
        if (active) setStatus('ok')
      } catch {
        if (active) setStatus('error')
      } finally {
        window.clearTimeout(timeout)
      }
    }
    void checkConnection()
    return () => {
      active = false
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [])

  return (
    <p className={`status ${status}`} role="status" aria-live="polite">
      {status === 'loading' && 'Comprobando conexión…'}
      {status === 'ok' && 'Conexión disponible.'}
      {status === 'error' && 'No se pudo conectar. Recarga la página para volver a intentarlo.'}
    </p>
  )
}
