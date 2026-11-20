import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from 'react-router'
import HealthStatus from './HealthStatus'
import { api, ApiError, hasToken, roleLabels, setToken, setUnauthorizedHandler, type Role, type TokenResponse, type User } from './api'
import { Consulta } from './consulta'
import { Corpus } from './corpus'
import { Dashboard } from './dashboard'
import { Generacion } from './generacion'
import { Historial } from './historial'
import { Examen, Feedback } from './screens'

const STUDY: Role[] = ['student', 'teacher']

// Matriz rol → pantalla según docs/api-contract.md; el backend aplica los permisos reales (403).
// El orden importa: `/` lleva a la primera pantalla permitida (el Panel para el administrador).
const screens: { path: string; label: string; roles: Role[]; element: ReactNode; icon: ReactNode }[] = [
  { path: 'dashboard', label: 'Panel', roles: ['admin'], element: <Dashboard />, icon: <path d="M4 4h7v7H4zm9 0h7v4h-7zm0 6h7v10h-7zM4 13h7v7H4z" /> },
  { path: 'consulta', label: 'Consulta', roles: STUDY, element: <Consulta />, icon: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></> },
  { path: 'generacion', label: 'Generación', roles: STUDY, element: <Generacion />, icon: <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zm0 0v6h6M8 13h8m-8 4h5" /> },
  { path: 'corpus', label: 'Corpus', roles: ['teacher', 'admin'], element: <Corpus />, icon: <path d="M4 19.5V5a2 2 0 0 1 2-2h14v15H6.5A2.5 2.5 0 0 0 4 20.5 2.5 2.5 0 0 0 6.5 23H20M8 7h8" /> },
  { path: 'historial', label: 'Historial', roles: STUDY, element: <Historial />, icon: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></> },
  { path: 'examen', label: 'Examen', roles: STUDY, element: <Examen />, icon: <path d="M10 6h10M10 12h10M10 18h10M3 6l1.5 1.5L7 5m-4 7 1.5 1.5L7 11m-4 7 1.5 1.5L7 17" /> },
  { path: 'feedback', label: 'Feedback', roles: ['student', 'teacher', 'admin'], element: <Feedback />, icon: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /> },
]

/** Icono de trazo decorativo; el texto contiguo da el nombre accesible. */
function Icon({ children }: { children: ReactNode }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{children}</svg>
}

// Columnas de un ateneo clásico: marca de la aplicación.
const logo = <Icon><path d="M3 9.5 12 4l9 5.5M5 10v8m4.67-8v8m4.66-8v8M19 10v8M3 20.5h18" /></Icon>

export default function App() {
  // undefined: comprobando el token guardado con /auth/me; null: sin sesión.
  const [user, setUser] = useState<User | null | undefined>(() => (hasToken() ? undefined : null))
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setExpired(true)
      setUser(null)
    })
    if (!hasToken()) return
    let active = true
    api<User>('/auth/me')
      .then((me) => active && setUser(me))
      // 401 ya pasa por el manejador; otros fallos (red, 5xx) obligan a entrar de nuevo.
      .catch(() => active && setUser(null))
    return () => {
      active = false
    }
  }, [])

  async function logout() {
    try {
      await api('/auth/logout', { method: 'POST' })
    } catch {
      // El token se descarta igualmente en el cliente.
    } finally {
      setToken(null)
      setExpired(false)
      setUser(null)
    }
  }

  if (user === undefined) {
    return (
      <main className="boot">
        <p role="status" className="loading">Comprobando la sesión…</p>
      </main>
    )
  }

  const allowed = user ? screens.filter((screen) => screen.roles.includes(user.role)) : []

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <ReturnToIntended /> : <Login expired={expired} onLogin={(next) => { setExpired(false); setUser(next) }} />}
      />
      <Route element={user ? <Layout user={user} allowed={allowed} onLogout={logout} /> : <RedirectToLogin />}>
        <Route index element={<Navigate to={`/${allowed[0]?.path ?? 'feedback'}`} replace />} />
        {screens.map((screen) => (
          <Route
            key={screen.path}
            path={screen.path}
            element={allowed.includes(screen) ? screen.element : <Message title="Acceso no permitido" text="Tu rol no tiene acceso a esta pantalla." />}
          />
        ))}
        <Route path="*" element={<Message title="Página no encontrada" text="La dirección no existe." />} />
      </Route>
    </Routes>
  )
}

function RedirectToLogin() {
  const location = useLocation()
  return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
}

// Tras entrar, vuelve a la ruta que pidió el usuario antes de ser redirigido al login.
function ReturnToIntended() {
  const location = useLocation()
  return <Navigate to={(location.state as { from?: string } | null)?.from ?? '/'} replace />
}

function Login({ expired, onLogin }: { expired: boolean; onLogin: (user: User) => void }) {
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const errorRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setPending(true)
    setError(null)
    try {
      const result = await api<TokenResponse>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: data.get('email'), password: data.get('password') }),
      })
      setToken(result.access_token)
      onLogin(result.user)
    } catch (err) {
      setPending(false)
      // Mensaje genérico: no distingue correo inexistente de contraseña errónea.
      setError(err instanceof ApiError && (err.status === 401 || err.status === 422)
        ? 'Correo o contraseña incorrectos.'
        : err instanceof ApiError && err.status === 429
          ? err.message
          : 'No se pudo iniciar sesión. Inténtalo de nuevo más tarde.')
    }
  }

  const describedBy = error ? 'login-error' : undefined

  return (
    <main className="login">
      <div className="login-brand">
        {logo}
        <p className="eyebrow">DERECHO · UNIVERSIDAD DE PINAR DEL RÍO</p>
        <h1 className="brand">Ateneo</h1>
        <p className="intro">Un espacio para consultar, comprender y practicar.</p>
      </div>
      <div className="login-card">
        <h2>Iniciar sesión</h2>
        {expired && <p className="status error" role="alert">Tu sesión ha caducado. Vuelve a entrar para continuar.</p>}
        <form onSubmit={submit}>
          <label>
            Correo electrónico
            <input name="email" type="email" autoComplete="username" required maxLength={320} aria-invalid={!!error} aria-describedby={describedBy} />
          </label>
          <label>
            Contraseña
            <input name="password" type="password" autoComplete="current-password" required maxLength={200} aria-invalid={!!error} aria-describedby={describedBy} />
          </label>
          {error && <p id="login-error" className="status error" role="alert" tabIndex={-1} ref={errorRef}>{error}</p>}
          <button type="submit" disabled={pending}>{pending ? 'Entrando…' : 'Entrar'}</button>
        </form>
        <footer>
          <HealthStatus />
        </footer>
      </div>
    </main>
  )
}

function Layout({ user, allowed, onLogout }: { user: User; allowed: typeof screens; onLogout: () => void }) {
  const { pathname } = useLocation()
  const mainRef = useRef<HTMLElement>(null)

  // Lleva el foco al contenido al cambiar de pantalla para lectores de pantalla y teclado.
  useEffect(() => mainRef.current?.focus(), [pathname])

  return (
    <div className="shell">
      <a className="skip" href="#contenido">Saltar al contenido</a>
      <header className="topbar">
        <p className="logo">{logo}Ateneo</p>
        <p className="session">
          <span className="avatar" aria-hidden="true">{user.full_name.trim().charAt(0).toUpperCase()}</span>
          <span className="session-name">{user.full_name}</span>
          <span className="badge role">{roleLabels[user.role]}</span>
          <button type="button" className="secondary small" onClick={onLogout}>
            <Icon><path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4m-5-3 5-5-5-5m5 5H3" /></Icon>
            <span className="label">Cerrar sesión</span>
          </button>
        </p>
      </header>
      <nav className="sidebar" aria-label="Principal">
        <ul>
          {allowed.map((screen) => (
            <li key={screen.path}><NavLink to={`/${screen.path}`}><Icon>{screen.icon}</Icon>{screen.label}</NavLink></li>
          ))}
        </ul>
      </nav>
      <main id="contenido" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
      <footer>
        <HealthStatus />
        <p>Proyecto Ateneo</p>
      </footer>
    </div>
  )
}

function Message({ title, text }: { title: string; text: string }) {
  return (
    <>
      <h1>{title}</h1>
      <p>{text}</p>
    </>
  )
}
