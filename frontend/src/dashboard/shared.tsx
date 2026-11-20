import { pageSize } from './labels'

/** Estados de carga, error y vacío de una lista, como en el resto de pantallas. */
export function ListState({ loading, error, empty, onRetry, what }: { loading: boolean; error: string; empty: boolean; onRetry: () => void; what: string }) {
  if (loading) return <p role="status" className="loading">Cargando {what}…</p>
  if (error) {
    return (
      <>
        <p className="status error" role="alert">{error}</p>
        <button type="button" className="secondary" onClick={onRetry}>Reintentar</button>
      </>
    )
  }
  if (empty) return <p role="status" className="empty">No hay {what} con estos filtros.</p>
  return null
}

/** Paginación con `limit = pageSize + 1`: la fila extra indica que hay página siguiente. */
export function Pager({ offset, rows, onChange, label }: { offset: number; rows: unknown[] | null; onChange: (offset: number) => void; label: string }) {
  const more = !!rows && rows.length > pageSize
  if (offset === 0 && !more) return null
  return (
    <div className="actions pager" role="group" aria-label={label}>
      <button type="button" className="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - pageSize))}>Anterior</button>
      <button type="button" className="secondary" disabled={!more} onClick={() => onChange(offset + pageSize)}>Siguiente</button>
    </div>
  )
}

export function UserCell({ user }: { user: { email: string; full_name: string } | null }) {
  if (!user) return <span className="note">Cuenta eliminada</span>
  return <>{user.full_name}<br /><span className="note">{user.email}</span></>
}
