import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'

/**
 * GET de `path` (null: no pide nada). Al cambiar `path` vuelve a «cargando»;
 * `reload()` repite la petición manteniendo los datos anteriores hasta que llegan los nuevos.
 */
export function useApi<T>(path: string | null) {
  const [result, setResult] = useState<{ path: string; data: T | null; error: string } | null>(null)
  const [count, setCount] = useState(0)

  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    api<T>(path, { signal: controller.signal }).then(
      (data) => !controller.signal.aborted && setResult({ path, data, error: '' }),
      (err: unknown) => !controller.signal.aborted && setResult({ path, data: null, error: errorMessage(err) }),
    )
    return () => controller.abort()
  }, [path, count])

  const reload = useCallback(() => setCount((n) => n + 1), [])
  const current = result && result.path === path ? result : null
  return {
    data: current?.data ?? null,
    error: current?.error ?? '',
    loading: !!path && !current,
    reload,
  }
}
