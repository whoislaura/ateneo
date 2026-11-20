import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, roleLabels, type Role } from '../api'
import type { AdminUser, AdminUserCreate } from '../admin-api'
import { actionError, dateTime, pageSize } from './labels'
import { ListState, Pager } from './shared'
import { useApi } from './useApi'

type Action = { kind: 'role' | 'toggle' | 'password' | 'sessions'; user: AdminUser }

const roles = Object.entries(roleLabels) as [Role, string][]

function RoleOptions() {
  return roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)
}

export function Cuentas() {
  const [query, setQuery] = useState({ q: '', role: '', offset: 0 })
  const params = new URLSearchParams({ limit: String(pageSize + 1), offset: String(query.offset) })
  if (query.q) params.set('q', query.q)
  if (query.role) params.set('role', query.role)
  const { data: users, error, loading, reload } = useApi<AdminUser[]>(`/admin/users?${params}`)

  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [notice, setNotice] = useState('')
  const [action, setAction] = useState<Action | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionErr, setActionErr] = useState('')
  const dialogRef = useRef<HTMLDialogElement>(null)
  const noticeRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (action && !dialog?.open) dialog?.showModal()
    if (!action && dialog?.open) dialog.close()
  }, [action])

  useEffect(() => {
    if (notice) noticeRef.current?.focus()
  }, [notice])

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setQuery({ q: String(data.get('q') ?? '').trim(), role: String(data.get('role') ?? ''), offset: 0 })
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const body: AdminUserCreate = {
      email: String(data.get('email')).trim(),
      full_name: String(data.get('full_name')).trim(),
      role: data.get('role') as Role,
      password: String(data.get('password')),
    }
    setCreating(true)
    setCreateError('')
    setNotice('')
    try {
      const user = await api<AdminUser>('/admin/users', { method: 'POST', body: JSON.stringify(body) })
      form.reset()
      setNotice(`Cuenta creada para ${user.email}.`)
      reload()
    } catch (err) {
      setCreateError(actionError(err))
    } finally {
      setCreating(false)
    }
  }

  function open(next: Action) {
    setActionErr('')
    setAction(next)
  }

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!action) return
    const data = new FormData(event.currentTarget)
    const { kind, user } = action
    const path = `/admin/users/${user.id}`
    setBusy(true)
    setActionErr('')
    try {
      if (kind === 'role') await api(path, { method: 'PATCH', body: JSON.stringify({ role: data.get('role') }) })
      if (kind === 'toggle') await api(path, { method: 'PATCH', body: JSON.stringify({ is_active: !user.is_active }) })
      if (kind === 'password') await api(`${path}/password`, { method: 'POST', body: JSON.stringify({ password: data.get('password') }) })
      if (kind === 'sessions') await api(`${path}/sessions`, { method: 'DELETE' })
      setAction(null)
      setNotice({
        role: `Rol de ${user.full_name} actualizado.`,
        toggle: `Cuenta de ${user.full_name} ${user.is_active ? 'desactivada' : 'activada'}.`,
        password: `Contraseña de ${user.full_name} restablecida; sus sesiones se han cerrado.`,
        sessions: `Sesiones de ${user.full_name} cerradas.`,
      }[kind])
      reload()
    } catch (err) {
      setActionErr(actionError(err))
    } finally {
      setBusy(false)
    }
  }

  const dangerous = action && (action.kind !== 'toggle' || action.user.is_active) && action.kind !== 'role'

  return (
    <>
      <section className="card" aria-labelledby="cuentas-nueva">
        <h2 id="cuentas-nueva">Crear cuenta</h2>
        <form onSubmit={create} aria-busy={creating}>
          <fieldset className="plain" disabled={creating}>
            <div className="fields">
              <label>Correo electrónico<input name="email" type="email" required maxLength={320} autoComplete="off" /></label>
              <label>Nombre completo<input name="full_name" required maxLength={200} autoComplete="off" /></label>
              <label>Rol<select name="role" defaultValue="student"><RoleOptions /></select></label>
              <label>
                Contraseña inicial
                <input name="password" type="password" required minLength={8} maxLength={200} autoComplete="new-password" aria-describedby="cuentas-pass-help" />
              </label>
            </div>
            <p id="cuentas-pass-help" className="note">Mínimo 8 caracteres. Comunícala a la persona por un canal seguro.</p>
          </fieldset>
          <button type="submit" disabled={creating}>{creating ? 'Creando…' : 'Crear cuenta'}</button>
          {createError && <p className="status error" role="alert">{createError}</p>}
        </form>
      </section>

      <p role="status" className={notice ? 'status ok' : undefined} tabIndex={-1} ref={noticeRef}>{notice}</p>

      <section className="card" aria-labelledby="cuentas-lista">
        <h2 id="cuentas-lista">Cuentas</h2>
        <form onSubmit={filter} aria-label="Filtrar cuentas">
          <div className="fields">
            <label>Buscar por correo o nombre<input name="q" type="search" maxLength={200} /></label>
            <label>Rol<select name="role" defaultValue=""><option value="">Todos</option><RoleOptions /></select></label>
          </div>
          <button type="submit" className="secondary">Filtrar</button>
        </form>

        <ListState loading={loading} error={error} empty={users?.length === 0} onRetry={reload} what="cuentas" />
        {users && users.length > 0 && (
          <div className="table-wrap" role="region" aria-label="Cuentas" tabIndex={0}>
            <table>
              <caption>Cuentas</caption>
              <thead>
                <tr>
                  <th scope="col">Nombre</th><th scope="col">Correo</th><th scope="col">Rol</th><th scope="col">Estado</th>
                  <th scope="col">Sesiones</th><th scope="col">Alta</th><th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {users.slice(0, pageSize).map((user) => (
                  <tr key={user.id}>
                    <th scope="row">{user.full_name}</th>
                    <td>{user.email}</td>
                    <td><span className="badge role">{roleLabels[user.role]}</span></td>
                    <td><span className={`badge ${user.is_active ? 'success' : ''}`}>{user.is_active ? 'Activa' : 'Inactiva'}</span></td>
                    <td>{user.active_sessions}</td>
                    <td><time dateTime={user.created_at}>{dateTime.format(new Date(user.created_at))}</time></td>
                    <td>
                      <div className="actions">
                        <button type="button" className="secondary small" onClick={() => open({ kind: 'role', user })} aria-label={`Cambiar rol de ${user.full_name}`}>Rol</button>
                        <button
                          type="button" className={`secondary small${user.is_active ? ' danger' : ''}`} onClick={() => open({ kind: 'toggle', user })}
                          aria-label={`${user.is_active ? 'Desactivar' : 'Activar'} la cuenta de ${user.full_name}`}
                        >
                          {user.is_active ? 'Desactivar' : 'Activar'}
                        </button>
                        <button type="button" className="secondary small" onClick={() => open({ kind: 'password', user })} aria-label={`Restablecer la contraseña de ${user.full_name}`}>Contraseña</button>
                        <button
                          type="button" className="secondary small danger" disabled={user.active_sessions === 0}
                          onClick={() => open({ kind: 'sessions', user })} aria-label={`Cerrar las sesiones de ${user.full_name}`}
                        >
                          Cerrar sesiones
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager offset={query.offset} rows={users} onChange={(offset) => setQuery({ ...query, offset })} label="Paginación de cuentas" />
      </section>

      <dialog ref={dialogRef} aria-labelledby="cuentas-dialog-title" aria-describedby="cuentas-dialog-text" onClose={() => setAction(null)}>
        {action && (
          <form onSubmit={run} aria-busy={busy}>
            <h2 id="cuentas-dialog-title">
              {{
                role: 'Cambiar rol',
                toggle: action.user.is_active ? 'Desactivar cuenta' : 'Activar cuenta',
                password: 'Restablecer contraseña',
                sessions: 'Cerrar sesiones',
              }[action.kind]}
            </h2>
            <p id="cuentas-dialog-text">
              {{
                role: `Nuevo rol para ${action.user.full_name} (${action.user.email}).`,
                toggle: action.user.is_active
                  ? `${action.user.full_name} no podrá entrar y se cerrarán sus sesiones abiertas.`
                  : `${action.user.full_name} podrá volver a entrar.`,
                password: `Se cerrarán las sesiones abiertas de ${action.user.full_name}. Comunícale la nueva contraseña por un canal seguro.`,
                sessions: `Se cerrarán las sesiones abiertas de ${action.user.full_name} (${action.user.active_sessions}); tendrá que volver a entrar.`,
              }[action.kind]}
            </p>
            {action.kind === 'role' && (
              <label>Rol<select name="role" defaultValue={action.user.role}><RoleOptions /></select></label>
            )}
            {action.kind === 'password' && (
              <label>
                Nueva contraseña
                <input name="password" type="password" required minLength={8} maxLength={200} autoComplete="new-password" aria-describedby="cuentas-dialog-help" />
                <span id="cuentas-dialog-help" className="note">Mínimo 8 caracteres.</span>
              </label>
            )}
            {actionErr && <p className="status error" role="alert">{actionErr}</p>}
            <div className="actions">
              <button type="button" className="secondary" autoFocus disabled={busy} onClick={() => setAction(null)}>Cancelar</button>
              <button type="submit" className={dangerous ? 'danger' : undefined} disabled={busy}>
                {busy ? 'Aplicando…' : { role: 'Cambiar rol', toggle: action.user.is_active ? 'Desactivar' : 'Activar', password: 'Restablecer', sessions: 'Cerrar sesiones' }[action.kind]}
              </button>
            </div>
          </form>
        )}
      </dialog>
    </>
  )
}
