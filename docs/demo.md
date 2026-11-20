# Guía de demostración

Cómo poner en marcha la demo, en Render o en local, y un recorrido rápido para comprobarla. Con el proveedor `fake` no hacen falta claves de IA ni corpus oficial. Para una reunión con el cliente (preparación, agenda, guion por rol, aceptación y feedback) usar el [kit de revisión con el cliente](revision-cliente.md).

## Demo en Render

Entorno ya desplegado en https://ateneo-web.onrender.com (montaje en [despliegue](deployment.md#demo-en-render)). Tiene las cuentas `admin@upr.edu.cu`, `profe@upr.edu.cu` y `estudiante@upr.edu.cu` y el corpus de muestra cargado; las contraseñas las guarda el equipo fuera del repositorio.

- La API se duerme tras 15 min sin uso y tarda alrededor de 1 min en despertar. Abrir la web antes de usarla y esperar a que el pie muestre «Conexión disponible.».
- Comprobación: `curl -s https://ateneo-web.onrender.com/api/v1/health`.
- Si falta el corpus, subirlo como profesor según [Corpus de muestra](#corpus-de-muestra).

## Demo local con Docker

Plan B si Render no responde, o para trabajar sin red.

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

3. Abrir http://localhost:8080 y cargar el [corpus de muestra](#corpus-de-muestra).

4. Comprobaciones:

   ```sh
   curl -s http://localhost:8080/api/v1/health
   python infra/smoke.py
   ```

Limpieza:

```sh
docker compose down            # conserva la base
docker compose down --volumes  # borra usuarios, corpus e historial locales
```

## Corpus de muestra

Generar los PDF sintéticos (también hacen falta en el equipo del presentador para subir material en vivo):

```sh
PYTHONPATH=backend uv run --project backend python -c \
  "from pathlib import Path; from app.rag.sample import create_sample; print(create_sample(Path('/tmp/ateneo-demo')))"
```

Entrar con `profe@upr.edu.cu`, abrir **Corpus** y, en «Subir material», rellenar:

| Archivo | Identificador | Año | Asignatura | Tema |
|---|---|---|---|---|
| `muestra-a.pdf` | `muestra-a` | 1.º año | Asignatura ficticia A | Biblioteca |
| `muestra-b.pdf` | `muestra-b` | 4.º año | Asignatura ficticia B | Evaluación |

`muestra-a` tiene una página en blanco a propósito: queda «Indexado con páginas sin texto». `muestra-c` contiene una instrucción incrustada para las pruebas de QA y no se usa en la demo.

## Recorrido rápido

Unos 5 minutos para comprobar que todo funciona. Tras entrar, la barra superior muestra el nombre, el rol y «Cerrar sesión», y el menú lateral solo las pantallas del rol.

1. **Consulta** (estudiante): pregunta `¿Dónde aparece azafrán?` → «Consultar». Abrir la cita [1] y pulsar «Ver en la página»: `muestra-a`, página 1, con el texto resaltado.
2. **Generación:** formato «Resumen», contenido `azafrán` → «Generar». Debe devolver contenido con cita.
3. **Historial:** aparecen la consulta y la generación en «Actividad reciente».
4. **Examen:** 1.º año, asignatura `Asignatura ficticia A`, 2 preguntas, dificultad «Media» → «Generar examen» y «Ver respuestas». Cada respuesta trae su cita.
5. **Feedback:** «Enviar feedback de este examen» → «Valoración» → «Enviar feedback».
6. **Admin:** entrar con `admin@upr.edu.cu`; el menú solo tiene Corpus y Feedback. En Corpus, marcar «Incluir retirados» y «Filtrar».

## Límites conocidos

- El proveedor `fake` es determinista y no demuestra calidad académica; solo el flujo y las citas.
- El corpus es sintético. Para la entrega real hay que cargar la bibliografía oficial y usar el proveedor configurado.
- No hay OCR: las páginas escaneadas quedan como `no_text`.
- El límite de subida es 20 MB en el backend y 25 MB en Nginx.
- La gestión de usuarios es por consola (`set-password`, `set-role`, `deactivate`, `list-users`).
