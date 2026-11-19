import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router'
import HealthStatus from './HealthStatus'
import { roleLabels, type Role } from './mock'
import { Consulta, Corpus, Examen, Feedback, Generacion, Historial } from './screens'

const ALL: Role[] = ['estudiante', 'profesor', 'administrador']

// Matriz rol → pantalla (docs/frontend.md). El backend (AT-08) aplicará los permisos reales.
const screens: { path: string; label: string; roles: Role[]; element: ReactNode }[] = [
  { path: 'consulta', label: 'Consulta', roles: ALL, element: <Consulta /> },
  { path: 'generacion', label: 'Generación', roles: ALL, element: <Generacion /> },
  { path: 'corpus', label: 'Corpus', roles: ['profesor', 'administrador'], element: <Corpus /> },
  { path: 'historial', label: 'Historial', roles: ['estudiante', 'profesor'], element: <Historial /> },
  { path: 'examen', label: 'Examen', roles: ['estudiante', 'profesor'], element: <Examen /> },
  { path: 'feedback', label: 'Feedback', roles: ALL, element: <Feedback /> },
]

const STORAGE_KEY = 'ateneo.role'

function readRole(): Role | null {
  try {
    const value = sessionStorage.getItem(STORAGE_KEY)
    return value && value in roleLabels ? (value as Role) : null
  } catch {
    return null
  }
}

export default function App() {
  // shortcut: rol simulado en sessionStorage sin autenticación; sustituir por la sesión real de AT-08/AT-20.
  const [role, setRole] = useState<Role | null>(readRole)

  function changeRole(next: Role | null) {
    try {
      if (next) sessionStorage.setItem(STORAGE_KEY, next)
      else sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // Sin almacenamiento la sesión dura solo hasta recargar.
    }
    setRole(next)
  }

  return (
    <Routes>
      <Route path="/login" element={<Login onLogin={changeRole} />} />
      <Route element={role ? <Layout role={role} onLogout={() => changeRole(null)} /> : <RedirectToLogin />}>
        <Route index element={<Navigate to="/consulta" replace />} />
        {screens.map((screen) => (
          <Route
            key={screen.path}
            path={screen.path}
            element={role && screen.roles.includes(role) ? screen.element : <Message title="Acceso no permitido" text="Tu rol no tiene acceso a esta pantalla." />}
          />
        ))}
        <Route path="*" element={<Message title="Página no encontrada" text="La dirección no existe." />} />
      </Route>
    </Routes>
  )
}

function RedirectToLogin() {
  const location = useLocation()
  return <Navigate to="/login" replace state={{ from: location.pathname }} />
}

function Login({ onLogin }: { onLogin: (role: Role) => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [role, setRole] = useState<Role>('estudiante')
  const from = (location.state as { from?: string } | null)?.from ?? '/consulta'

  return (
    <main className="login">
      <p className="eyebrow">DERECHO · UNIVERSIDAD DE PINAR DEL RÍO</p>
      <h1 className="brand">Ateneo</h1>
      <p className="intro">Un espacio para consultar, comprender y practicar.</p>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onLogin(role)
          navigate(from, { replace: true })
        }}
      >
        <fieldset>
          <legend>Entrar como (simulado)</legend>
          {ALL.map((value) => (
            <label key={value} className="choice">
              <input type="radio" name="role" value={value} checked={role === value} onChange={() => setRole(value)} />
              {roleLabels[value]}
            </label>
          ))}
        </fieldset>
        <button type="submit">Entrar</button>
      </form>
      <footer>
        <HealthStatus />
      </footer>
    </main>
  )
}

function Layout({ role, onLogout }: { role: Role; onLogout: () => void }) {
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
            {screens.filter((screen) => screen.roles.includes(role)).map((screen) => (
              <li key={screen.path}><NavLink to={`/${screen.path}`}>{screen.label}</NavLink></li>
            ))}
          </ul>
        </nav>
        <p className="session">
          {roleLabels[role]} <button type="button" onClick={onLogout}>Cerrar sesión</button>
        </p>
      </header>
      <main id="contenido" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
      <footer>
        <HealthStatus />
        <p>Proyecto Ateneo · Pantallas de demostración con datos ficticios</p>
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
