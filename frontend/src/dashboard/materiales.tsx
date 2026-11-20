import { Link } from 'react-router'
import { documentStatusLabels as statusLabels, type CorpusDocument } from '../api'
import { dateTime } from './labels'
import { ListState } from './shared'
import { useApi } from './useApi'

export function Materiales() {
  const { data: docs, error, loading, reload } = useApi<CorpusDocument[]>('/documents?include_retired=true')
  const count = (status: CorpusDocument['status']) => docs?.filter((doc) => doc.status === status).length ?? 0

  return (
    <section className="card" aria-labelledby="materiales-lista">
      <h2 id="materiales-lista">Material del corpus</h2>
      <p className="note">
        Para subir, actualizar o retirar material usa la pantalla <Link to="/corpus">Corpus</Link>.
      </p>
      <ListState loading={loading} error={error} empty={docs?.length === 0} onRetry={reload} what="documentos" />
      {docs && docs.length > 0 && (
        <>
          <dl className="stats">
            {(['indexed', 'partial', 'retired'] as const).map((status) => (
              <div key={status} className="stat"><dt>{statusLabels[status]}</dt><dd>{count(status)}</dd></div>
            ))}
          </dl>
          <div className="table-wrap" role="region" aria-label="Documentos" tabIndex={0}>
            <table>
              <caption>Documentos, incluidos los retirados ({docs.length})</caption>
              <thead>
                <tr>
                  <th scope="col">Título</th><th scope="col">Identificador</th><th scope="col">Año</th><th scope="col">Asignatura</th>
                  <th scope="col">Tema</th><th scope="col">Estado</th><th scope="col">Actualizado</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((doc) => (
                  <tr key={doc.id}>
                    <th scope="row">{doc.title}</th><td><code>{doc.id}</code></td><td>{doc.year}.º</td><td>{doc.subject}</td><td>{doc.topic}</td>
                    <td><span className={`badge ${doc.status}`}>{statusLabels[doc.status]}</span></td>
                    <td><time dateTime={doc.updated_at}>{dateTime.format(new Date(doc.updated_at))}</time></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
