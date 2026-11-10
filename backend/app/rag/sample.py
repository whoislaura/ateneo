"""Genera material ficticio reproducible; ReportLab solo se instala en desarrollo."""

import json
from pathlib import Path


def create_sample(directory: Path) -> list[dict]:
    from reportlab.pdfgen.canvas import Canvas

    directory.mkdir(parents=True, exist_ok=True)
    definitions = [
        (
            "muestra-a",
            1,
            "Asignatura ficticia A",
            "Biblioteca",
            [
                [
                    "MATERIAL SINTÉTICO - SIN VALIDEZ ACADÉMICA",
                    "La biblioteca ficticia conserva un catálogo de libros y páginas.",
                    "El término exclusivo de esta página es azafrán.",
                ],
                [],
                [
                    "MATERIAL SINTÉTICO - PÁGINA DE PRUEBA",
                    "La página tercera describe el préstamo ficticio de cuadernos.",
                ]
                + [
                    f"Párrafo {n}: conservación, edición y revisión de documentos sintéticos."
                    for n in range(1, 35)
                ],
            ],
        ),
        (
            "muestra-b",
            4,
            "Asignatura ficticia B",
            "Evaluación",
            [
                [
                    "MATERIAL SINTÉTICO - SIN VALIDEZ ACADÉMICA",
                    "Esta evaluación ficticia utiliza una rúbrica de colores.",
                    "El término exclusivo es turquesa. La biblioteca sirve como ejemplo.",
                ],
                [
                    "La segunda página explica una revisión ficticia de ejercicios.",
                    "Cada ejercicio de prueba tiene una referencia y una página.",
                ],
            ],
        ),
    ]
    targets = [
        directory / (identifier + suffix)
        for identifier, *_ in definitions
        for suffix in (".pdf", ".json")
    ]
    if any(path.exists() for path in targets):
        raise ValueError("La muestra ya existe; elige una carpeta nueva para no sobrescribirla.")
    outputs = []
    for identifier, year, subject, topic, pages in definitions:
        pdf_path = directory / f"{identifier}.pdf"
        canvas = Canvas(str(pdf_path), pagesize=(595, 842), invariant=1, pageCompression=1)
        canvas.setTitle("Muestra sintética Ateneo: " + identifier)
        for lines in pages:
            text = canvas.beginText(40, 800)
            text.setFont("Helvetica", 11)
            text.setLeading(18)
            for line in lines:
                text.textLine(line)
            canvas.drawText(text)
            canvas.showPage()
        canvas.save()
        metadata = {
            "document_id": identifier,
            "title": "Muestra sintética " + identifier,
            "year": year,
            "subject": subject,
            "topic": topic,
        }
        metadata_path = directory / f"{identifier}.json"
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        outputs.append({"pdf": str(pdf_path), "metadata": str(metadata_path)})
    return outputs
