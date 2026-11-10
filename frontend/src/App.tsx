import { useEffect, useState } from 'react'

export default function App() {
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
    <main>
      <p className="eyebrow">DERECHO · UNIVERSIDAD DE PINAR DEL RÍO</p>
      <h1>Ateneo</h1>
      <p className="intro">Un espacio para consultar, comprender y practicar.</p>
      <section aria-labelledby="progress-title">
        <h2 id="progress-title">Estamos preparando tu asistente académico</h2>
        <p>Próximamente podrás estudiar con la bibliografía de tus asignaturas y consultar sus fuentes.</p>
        <p className={`status ${status}`} role="status" aria-live="polite">
          {status === 'loading' && 'Comprobando conexión…'}
          {status === 'ok' && 'Conexión disponible.'}
          {status === 'error' && 'No se pudo conectar. Recarga la página para volver a intentarlo.'}
        </p>
      </section>
      <footer>Proyecto Ateneo · En preparación</footer>
    </main>
  )
}
