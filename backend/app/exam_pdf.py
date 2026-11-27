"""CU-06: PDF del examen (para el estudiante, sin soluciones) y clave de corrección (profesor).

Fuente Bitstream Vera, que viene con reportlab y cubre el español (tildes, ñ, ¿¡, «»).
"""

import io
from datetime import datetime
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Exam, ExamQuestion

INSTITUTION = (
    "Universidad de Pinar del Río · Facultad de Ciencias Sociales y Humanísticas "
    "· Carrera de Derecho"
)
INSTRUCTIONS = (
    "Escriba su nombre y grupo antes de comenzar.",
    "Lea con atención cada pregunta; la puntuación de cada una figura junto al enunciado.",
    "Responda en los espacios indicados, con letra clara y con argumentos jurídicos precisos.",
    "En las preguntas de test marque una sola opción; en las de verdadero o falso, marque "
    "la casilla y justifique la respuesta.",
    "No se permite el uso de materiales de consulta ni de dispositivos electrónicos.",
)
KIND_LABEL = {
    "completion": "Completar",
    "development": "Desarrollo",
    "case": "Caso práctico",
    "multiple_choice": "Test",
    "true_false": "Verdadero o falso",
}
# Líneas en blanco para responder, por tipo.
LINES = {"development": 9, "case": 14, "true_false": 3, "completion": 2}
FONT = "Vera"
GREY = colors.HexColor("#555555")


def register_fonts() -> None:
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    folder = reportlab.__path__[0] + "/fonts/"
    for name, file in (("", "Vera"), ("-Bold", "VeraBd"), ("-Italic", "VeraIt")):
        pdfmetrics.registerFont(TTFont(FONT + name, f"{folder}{file}.ttf"))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT + "-Bold", italic=FONT + "-Italic")


def style(name: str, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, **({"fontName": FONT, "fontSize": 10, "leading": 14} | kw))


STYLES = {
    "body": style("body"),
    "small": style("small", fontSize=8.5, leading=11, textColor=GREY),
    "centre": style("centre", alignment=TA_CENTER, fontSize=9, leading=12, textColor=GREY),
    "title": style("title", alignment=TA_CENTER, fontName=FONT + "-Bold", fontSize=15, leading=19),
    "h2": style("h2", fontName=FONT + "-Bold", fontSize=10.5, spaceBefore=4),
    "option": style("option", leftIndent=0),
}


def para(text: str, name: str = "body") -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), STYLES[name])


def score(value: float) -> str:
    return f"{value:.1f}".replace(".", ",").removesuffix(",0") + (" pt" if value == 1 else " pts")


class Box(Flowable):
    """Casilla vacía para marcar."""

    def __init__(self, size: float = 9):
        super().__init__()
        self.width = self.height = size

    def draw(self):
        self.canv.setLineWidth(0.8)
        self.canv.rect(0, 0, self.width, self.height)


class Lines(Flowable):
    """Renglones en blanco para responder."""

    def __init__(self, count: int, gap: float = 0.75 * cm):
        super().__init__()
        self.count, self.gap = count, gap

    def wrap(self, width, height):
        self.width = width
        return width, self.count * self.gap

    def draw(self):
        self.canv.setStrokeColor(colors.HexColor("#999999"))
        self.canv.setLineWidth(0.5)
        for i in range(self.count):
            y = (i + 0.2) * self.gap
            self.canv.line(0, y, self.width, y)


class NumberedCanvas(Canvas):
    """Pie con «Página n de N»; el total se conoce al final."""

    def __init__(self, *args, footer: str = "", **kw):
        super().__init__(*args, **kw)
        self.footer, self.saved = footer, []

    def showPage(self):
        self.saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self.saved)
        for state in self.saved:
            self.__dict__.update(state)
            self.setFont(FONT, 8)
            self.setFillColor(GREY)
            self.drawString(2 * cm, 1.2 * cm, self.footer)
            self.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def header(exam: Exam, key: bool) -> list:
    created = exam.created_at or datetime.now()
    rows = [
        [f"Asignatura: {exam.subject}", f"Año: {exam.year}.º"],
        [f"Tema: {exam.topic or 'General'}", f"Fecha: {created:%d/%m/%Y}"],
        [
            f"Duración: {exam.duration_minutes} minutos",
            f"Puntuación total: {score(exam.total_points)}",
        ],
    ]
    table = Table([[para(a), para(b)] for a, b in rows], colWidths=[10 * cm, 7 * cm])
    table.setStyle(
        TableStyle([("BOX", (0, 0), (-1, -1), 0.6, GREY), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    )
    out = [para(INSTITUTION, "centre"), Spacer(1, 6)]
    out.append(Paragraph("CLAVE DE CORRECCIÓN" if key else "EXAMEN", STYLES["title"]))
    out += [
        Spacer(1, 2),
        para(f"{exam.subject}" + (" · uso exclusivo del profesor" if key else ""), "centre"),
    ]
    out += [Spacer(1, 8), table, Spacer(1, 8)]
    if not key:
        name = Table(
            [[para("Nombre y apellidos:"), "", para("Grupo:"), ""]],
            colWidths=[4.2 * cm, 7.4 * cm, 1.8 * cm, 3.6 * cm],
        )
        name.setStyle(
            TableStyle(
                [("LINEBELOW", (1, 0), (1, 0), 0.6, GREY), ("LINEBELOW", (3, 0), (3, 0), 0.6, GREY)]
            )
        )
        out += [name, Spacer(1, 10), para("Instrucciones generales", "h2")]
        out += [para(f"{n}. {text}", "small") for n, text in enumerate(INSTRUCTIONS, 1)]
        out.append(Spacer(1, 8))
    return out


def question_block(question: ExamQuestion) -> list:
    head = f"{question.position}. [{KIND_LABEL[question.kind]} · {score(question.points)}]"
    parts: list = [para(head, "h2"), para(question.statement), Spacer(1, 4)]
    if question.kind == "multiple_choice":
        rows = [
            [Box(), para(f"{letter}) {text}", "option")]
            for letter, text in zip("ABCD", question.options or [], strict=False)
        ]
        table = Table(rows, colWidths=[0.7 * cm, 16 * cm])
        table.setStyle(
            TableStyle(
                [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2)]
            )
        )
        parts.append(table)
    elif question.kind == "true_false":
        table = Table(
            [[Box(), para("Verdadero"), Box(), para("Falso")]],
            colWidths=[0.7 * cm, 3 * cm, 0.7 * cm, 3 * cm],
            hAlign="LEFT",
        )
        parts += [table, para("Justifique:", "small")]
    if lines := LINES.get(question.kind):
        parts.append(Lines(lines))
    return [KeepTogether(parts), Spacer(1, 10)]


def key_block(question: ExamQuestion) -> list:
    head = f"{question.position}. [{KIND_LABEL[question.kind]} · {score(question.points)}]"
    parts: list = [para(head, "h2"), para(question.statement)]
    for n, text in enumerate(question.options or [], 0):
        parts.append(para(f"{'ABCD'[n]}) {text}", "small"))
    parts += [Spacer(1, 3), para("Solución", "h2"), para(question.answer)]
    if question.criteria:
        parts += [para("Criterio de corrección", "h2"), para(question.criteria)]
    parts.append(para("Fuentes", "h2"))
    for c in question.citations:
        page = c.page_label or c.page_number
        quote = c.quote if len(c.quote) <= 220 else c.quote[:217] + "…"
        parts.append(para(f"[{c.position}] {c.document_title}, p. {page}: «{quote}»", "small"))
    return [*parts, Spacer(1, 12)]


def build(exam: Exam, key: bool) -> bytes:
    register_fonts()
    buffer = io.BytesIO()
    title = f"{'Clave' if key else 'Examen'} {exam.id} · {exam.subject}"
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=title, author="Ateneo",
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
    )  # fmt: skip
    story = header(exam, key)
    block = key_block if key else question_block
    for question in exam.questions:
        story += block(question)
    footer = f"{'Clave de corrección' if key else 'Examen'} · {exam.subject} · {exam.year}.º año"
    doc.build(story, canvasmaker=lambda *a, **kw: NumberedCanvas(*a, footer=footer, **kw))
    return buffer.getvalue()


def exam_pdf(exam: Exam) -> bytes:
    return build(exam, key=False)


def key_pdf(exam: Exam) -> bytes:
    return build(exam, key=True)
