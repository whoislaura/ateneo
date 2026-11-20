import { roleLabels, type Role } from '../api'
import type { AdminStats } from '../admin-api'
import { ListState } from './shared'
import { useApi } from './useApi'

const number = new Intl.NumberFormat('es')
const day = new Intl.DateTimeFormat('es', { weekday: 'short', day: 'numeric', timeZone: 'UTC' })
const series = [
  { key: 'queries', label: 'Consultas' },
  { key: 'generations', label: 'Generaciones' },
  { key: 'exams', label: 'Exámenes' },
] as const

function Stats({ items }: { items: [string, string | number][] }) {
  return (
    <dl className="stats">
      {items.map(([label, value]) => (
        <div key={label} className="stat"><dt>{label}</dt><dd>{typeof value === 'number' ? number.format(value) : value}</dd></div>
      ))}
    </dl>
  )
}

export function Resumen() {
  const { data, error, loading, reload } = useApi<AdminStats>('/admin/stats')

  if (!data) return <ListState loading={loading} error={error} empty={false} onRetry={reload} what="el resumen" />

  const { users, documents, activity } = data
  const answers = activity.queries + activity.generations
  const days = activity.last_7_days
  const max = Math.max(1, ...days.map((d) => d.queries + d.generations + d.exams))

  return (
    <>
      <section className="card" aria-labelledby="resumen-cuentas">
        <h2 id="resumen-cuentas">Cuentas</h2>
        <Stats items={[
          ['Total', users.total],
          ['Activas', users.active],
          ...(Object.keys(roleLabels) as Role[]).map((role): [string, number] => [roleLabels[role], users.by_role[role] ?? 0]),
        ]} />
      </section>

      <section className="card" aria-labelledby="resumen-materiales">
        <h2 id="resumen-materiales">Materiales</h2>
        <Stats items={[
          ['Activos', documents.active],
          ['Retirados', documents.retired],
          ['Páginas', documents.pages],
          ['Páginas sin texto', documents.pages_without_text],
        ]} />
      </section>

      <section className="card" aria-labelledby="resumen-actividad">
        <h2 id="resumen-actividad">Actividad</h2>
        <Stats items={[
          ['Consultas', activity.queries],
          ['Generaciones', activity.generations],
          ['Exámenes', activity.exams],
          ['Feedback', activity.feedback],
          ['Sin evidencia', answers ? `${Math.round((activity.no_evidence / answers) * 100)} %` : '—'],
        ]} />

        <h3 className="chart-title">Últimos 7 días</h3>
        {/* Gráfico solo visual; la tabla siguiente tiene los mismos datos para lectores de pantalla. */}
        <div className="bars" aria-hidden="true">
          {days.map((d) => (
            <div key={d.date} className="bar-col">
              <span className="bar-total">{d.queries + d.generations + d.exams}</span>
              <div className="bar">
                {[...series].reverse().map((s) => (
                  <span key={s.key} className={`seg ${s.key}`} style={{ height: `${(d[s.key] / max) * 100}%` }} />
                ))}
              </div>
              <span className="bar-label">{day.format(new Date(`${d.date}T00:00:00Z`))}</span>
            </div>
          ))}
        </div>
        <ul className="legend" aria-hidden="true">
          {series.map((s) => <li key={s.key} className={s.key}>{s.label}</li>)}
        </ul>
        <div className="table-wrap" role="region" aria-label="Actividad de los últimos 7 días" tabIndex={0}>
          <table>
            <caption>Actividad de los últimos 7 días (UTC)</caption>
            <thead>
              <tr><th scope="col">Día</th>{series.map((s) => <th key={s.key} scope="col">{s.label}</th>)}</tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date}>
                  <th scope="row"><time dateTime={d.date}>{day.format(new Date(`${d.date}T00:00:00Z`))}</time></th>
                  {series.map((s) => <td key={s.key}>{d[s.key]}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
