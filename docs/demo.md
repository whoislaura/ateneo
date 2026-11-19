# Guía de demostración

Recorrido de cierre con el stack local y el proveedor `fake`. No necesita claves de IA ni corpus oficial.

## Preparación

1. Arrancar el stack:

   ```sh
   cp .env.example .env
   docker compose up --build --wait
   ```

2. Crear las cuentas. La contraseña se pide por consola y no se guarda en el repositorio:

   ```sh
   docker compose exec api python -m app.auth create-user admin@upr.edu.cu --name "Admin Demo" --role admin
   docker compose exec api python -m app.auth create-user profe@upr.edu.cu --name "Profe Demo" --role teacher
   docker compose exec api python -m app.auth create-user estudiante@upr.edu.cu --name "Estudiante Demo" --role student
   ```

3. Generar los PDF sintéticos de muestra:

   ```sh
   PYTHONPATH=backend uv run --project backend python -c \
     "from pathlib import Path; from app.rag.sample import create_sample; print(create_sample(Path('/tmp/ateneo-demo')))"
   ```

4. Entrar como **Profe Demo** en http://localhost:8080, abrir **Corpus** y subir:

   | Archivo | Identificador | Año | Asignatura | Tema |
   |---|---|---|---|---|
   | `muestra-a.pdf` | `muestra-a` | 1 | Asignatura ficticia A | Biblioteca |
   | `muestra-b.pdf` | `muestra-b` | 4 | Asignatura ficticia B | Evaluación |

## Recorrido

1. **Consulta:** pregunta `¿Dónde aparece azafrán?` y abre la cita [1]. Debe mostrar `muestra-a`, página 1, con el texto resaltado.
2. **Generación:** formato Resumen, tema `azafrán`. Debe devolver contenido con cita.
3. **Historial:** comprobar las entradas de consulta y generación.
4. **Examen:** año 1, asignatura `Asignatura ficticia A`, 2 preguntas, dificultad Media. Generar, abrir el examen y pulsar **Ver respuestas**. Cada respuesta debe traer su cita.
5. **Feedback:** enviar una valoración al examen.
6. **Admin:** entrar con `admin@upr.edu.cu`, abrir Corpus y marcar **Incluir retirados**. El admin no tiene consulta ni exámenes por contrato.

## Comprobaciones rápidas

```sh
curl -s http://localhost:8080/api/v1/health
python infra/smoke.py
```

## Límites conocidos

- El proveedor `fake` es determinista y no demuestra calidad académica; solo el flujo y las citas.
- El corpus es sintético. Para la entrega real hay que cargar la bibliografía oficial y usar el proveedor configurado.
- No hay OCR: las páginas escaneadas quedan como `no_text`.
- El límite de subida es 20 MB en el backend y 25 MB en Nginx.
- La gestión de usuarios es por consola (`set-password`, `set-role`, `deactivate`, `list-users`).

## Limpieza

```sh
docker compose down          # conserva la base
docker compose down --volumes  # borra usuarios, corpus e historial locales
```
