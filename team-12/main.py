from PySide6.QtWidgets import (
    QMainWindow,
    QApplication,
    QWidget,
    QVBoxLayout,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QMenuBar,
    QDialog,
    QHBoxLayout,
    QLabel,
)
import datetime
from PySide6.QtGui import QAction, QImage, QPixmap, QColor, QBrush
from PySide6.QtCore import Qt
import sqlite3
import sys
from pathlib import Path
import pytesseract
from PIL import Image
import pandas as pd
import reportlab.lib.pagesizes as pagesizes
from reportlab.pdfgen import canvas

from ocr import ocr_image
from race_result import RaceResult


def export_excel(self):
    class_name = self.class_combo.currentText()
    if not class_name:
        return

    cursor = self.conn.cursor()
    cursor.execute(
        """
        SELECT p.name, p.position 
        FROM participants p
        JOIN races r ON p.race_id = r.id
        WHERE r.class_name = ?
        ORDER BY p.position
    """,
        (class_name,),
    )

    df = pd.DataFrame(cursor.fetchall(), columns=["Name", "Position"])
    df.to_excel(f"{class_name}_results.xlsx", index=False)


def export_pdf(self):
    class_name = self.class_combo.currentText()
    if not class_name:
        return

    cursor = self.conn.cursor()
    cursor.execute(
        """
        SELECT p.name, p.position 
        FROM participants p
        JOIN races r ON p.race_id = r.id
        WHERE r.class_name = ?
        ORDER BY p.position
    """,
        (class_name,),
    )

    pdf = canvas.Canvas(f"{class_name}_results.pdf", pagesize=pagesizes.A4)
    pdf.setFont("Helvetica", 12)
    y = 800
    for row in cursor.fetchall():
        pdf.drawString(100, y, f"{row[1]}. {row[0]}")
        y -= 20
        if y < 50:
            pdf.showPage()
            y = 800
    pdf.save()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Race Ratings")
        self.setGeometry(100, 100, 800, 600)

        # Database setup
        self.conn = sqlite3.connect("races.db")
        self.create_tables()

        # Central Widget
        central_widget = QWidget()
        self.layout = QVBoxLayout(central_widget)

        # Race Class Selector
        self.class_combo = QComboBox()
        self.populate_classes()
        self.layout.addWidget(self.class_combo)

        # Results Table
        self.results_table = QTableWidget()
        self.layout.addWidget(self.results_table)

        # Menu Bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        # Import Action
        self.image_loader_dialog = ImageLoaderDialog()
        import_action = QAction("Import Results", self)
        import_action.triggered.connect(self.image_loader_dialog.load_image)
        # import_action.triggered.connect(self.show_image_loader)
        file_menu.addAction(import_action)

        # Export Actions
        export_excel_a = QAction("Export to Excel", self)
        export_excel_a.triggered.connect(export_excel)
        # export_excel.triggered.connect(self.export_excel)
        file_menu.addAction(export_excel_a)

        export_pdf_a = QAction("Export to PDF", self)
        export_pdf_a.triggered.connect(export_pdf)
        # export_pdf.triggered.connect(self.export_pdf)
        file_menu.addAction(export_pdf_a)

        self.setCentralWidget(central_widget)
        self.show()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS races (
                id INTEGER PRIMARY KEY,
                class_name TEXT UNIQUE,
                date_added DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY,
                race_id INTEGER,
                name TEXT,
                position INTEGER,
                FOREIGN KEY(race_id) REFERENCES races(id)
            )
        """)
        self.conn.commit()

    def populate_classes(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT class_name FROM races")
        self.class_combo.clear()
        self.class_combo.addItems([row[0] for row in cursor.fetchall()])


class ImageLoaderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Results")
        self.setGeometry(200, 200, 1000, 600)

        layout = QHBoxLayout()

        # Image Preview
        self.image_label = QLabel()
        layout.addWidget(self.image_label, 50)

        # Editable Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Name", "Position"])
        layout.addWidget(self.table, 50)

        # Buttons
        self.load_btn = QPushButton("Load Image")
        self.load_btn.clicked.connect(self.load_image)
        layout.addWidget(self.load_btn)

        self.setLayout(layout)

    def load_image(self):
        self.table.clear()

        fname, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "", "Image Files (*.png *.jpg *.jpeg)"
        )
        if fname:
            # Load and display image
            image = QImage(fname)
            self.image_label.setPixmap(QPixmap.fromImage(image).scaledToWidth(500))

            self.show()
            # OCR Processing
            race_result = ocr_image(Path(fname))
            self.process_ocr_text(race_result)

    def _add_row(self, row_cnt, first, text, confidence, *, show_color=True):
        self.table.setItem(row_cnt, 0, QTableWidgetItem(str(first)))
        self.table.setItem(row_cnt, 1, QTableWidgetItem(str(text)))
        if show_color:
            qitem = QTableWidgetItem(f"{confidence / 100:.2f}")
            color = QColor(0, 255, 0)
            if 40 < confidence < 70:
                color = QColor(255, 255, 0)
            elif confidence < 40:
                color = QColor(255, 0, 0)
            qitem.setBackground(QBrush(color))
        else:
            qitem = QTableWidgetItem(str(confidence))

        qitem.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row_cnt, 2, qitem)

    def process_ocr_text(self, race_result: RaceResult):
        self.table.setRowCount(4 + len(race_result.full_participants))
        self.table.setColumnCount(3)

        self._add_row(0, "Класс моделей", *race_result.full_typ)
        date, conf = race_result.full_date
        date = date.strftime("%d.%m.%Y") if isinstance(date, datetime.date) else ""
        self._add_row(1, "Дата", date, conf)
        self._add_row(3, "Позиция", "Участник", "", show_color=False)

        for i, (participant, confidence) in enumerate(
            race_result.full_participants, start=4
        ):
            self._add_row(i, i - 3, participant, confidence)
            pos_item = self.table.item(i, 0)
            pos_item.setTextAlignment(Qt.AlignCenter)

        self.table.resizeColumnsToContents()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    sys.exit(app.exec())
