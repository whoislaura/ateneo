import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from 'react-router'
import HealthStatus from './HealthStatus'
import { api, ApiError, hasToken, roleLabels, setToken, setUnauthorizedHandler, type Role, type TokenResponse, type User } from './api'
import { Consulta } from './consulta'
import { Corpus } from './corpus'
import { Generacion } from './generacion'
import { Historial } from './historial'
import { Examen, Feedback } from './screens'

const STUDY: Role[] = ['student', 'teacher']

// Matriz rol → pantalla según docs/api-contract.md; el backend aplica los permisos reales (403).
const screens: { path: string; label: string; roles: Role[]; element: ReactNode }[] = [
  { path: 'consulta', label: 'Consulta', roles: STUDY, element: <Consulta /> },
  { path: 'generacion', label: 'Generación', roles: STUDY, element: <Generacion /> },
  { path: 'corpus', label: 'Corpus', roles: ['teacher', 'admin'], element: <Corpus /> },
  { path: 'historial', label: 'Historial', roles: STUDY, element: <Historial /> },
  { path: 'examen', label: 'Examen', roles: STUDY, element: <Examen /> },
  { path: 'feedback', label: 'Feedback', roles: ['student', 'teacher', 'admin'], element: <Feedback /> },
]

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
      <main>
        <p role="status">Comprobando la sesión…</p>
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
        : 'No se pudo iniciar sesión. Inténtalo de nuevo más tarde.')
    }
  }

  const describedBy = error ? 'login-error' : undefined

  return (
    <main className="login">
      <p className="eyebrow">DERECHO · UNIVERSIDAD DE PINAR DEL RÍO</p>
      <h1 className="brand">Ateneo</h1>
      <p className="intro">Un espacio para consultar, comprender y practicar.</p>
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
      <header>
        <p className="logo">Ateneo</p>
        <nav aria-label="Principal">
          <ul>
            {allowed.map((screen) => (
              <li key={screen.path}><NavLink to={`/${screen.path}`}>{screen.label}</NavLink></li>
            ))}
          </ul>
        </nav>
        <p className="session">
          {user.full_name} · {roleLabels[user.role]} <button type="button" onClick={onLogout}>Cerrar sesión</button>
        </p>
      </header>
      <main id="contenido" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
      <footer>
        <HealthStatus />
        <p>Proyecto Ateneo · Examen y feedback usan aún datos ficticios</p>
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
