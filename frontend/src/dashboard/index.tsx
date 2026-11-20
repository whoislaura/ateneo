import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { Consultas } from './consultas'
import { Cuentas } from './cuentas'
import { FeedbackAdmin } from './feedback'
import { Logs } from './logs'
import { Materiales } from './materiales'
import { Resumen } from './resumen'

const tabs: { id: string; label: string; panel: ReactNode }[] = [
  { id: 'resumen', label: 'Resumen', panel: <Resumen /> },
  { id: 'cuentas', label: 'Cuentas', panel: <Cuentas /> },
  { id: 'materiales', label: 'Materiales', panel: <Materiales /> },
  { id: 'consultas', label: 'Consultas', panel: <Consultas /> },
  { id: 'feedback', label: 'Feedback', panel: <FeedbackAdmin /> },
  { id: 'logs', label: 'Logs', panel: <Logs /> },
]

/** Panel de administración (solo rol admin). La pestaña activa vive en ?tab= para sobrevivir a una recarga. */
export function Dashboard() {
  const [params, setParams] = useSearchParams()
  const current = tabs.find((tab) => tab.id === params.get('tab')) ?? tabs[0]
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({})

  // En pantallas estrechas la lista de pestañas se desplaza: la activa queda a la vista.
  useEffect(() => {
    buttons.current[current.id]?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [current])

  function select(id: string) {
    setParams({ tab: id }, { replace: true })
  }

  // Patrón de pestañas WAI-ARIA con activación automática: flechas, Inicio y Fin.
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.indexOf(current)
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[event.key]
    if (next === undefined) return
    event.preventDefault()
    const tab = tabs[(next + tabs.length) % tabs.length]
    select(tab.id)
    buttons.current[tab.id]?.focus()
  }

  return (
    <>
      <h1>Panel de administración</h1>
      <div role="tablist" aria-label="Secciones del panel" className="tabs" onKeyDown={onKeyDown}>
        {tabs.map((tab) => (
          <button
            key={tab.id} type="button" role="tab" id={`tab-${tab.id}`} aria-controls={tab === current ? `panel-${tab.id}` : undefined}
            aria-selected={tab === current} tabIndex={tab === current ? 0 : -1}
            ref={(el) => { buttons.current[tab.id] = el }} onClick={() => select(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${current.id}`} aria-labelledby={`tab-${current.id}`} tabIndex={0} key={current.id}>
        {current.panel}
      </div>
    </>
  )
}
