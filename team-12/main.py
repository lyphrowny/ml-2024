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
from datetime import datetime
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
from itertools import chain
from collections import defaultdict

from ocr import ocr_image
from race_result import RaceResult


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
        hlayout = QHBoxLayout()
        hlayout.addWidget(self.class_combo, 80)
        # self.layout.addWidget(self.class_combo)

        self.show_btn = QPushButton("Show")
        self.show_btn.clicked.connect(self.build_table_result)
        hlayout.addWidget(self.show_btn, 20)
        self.layout.addLayout(hlayout)

        # Results Table
        self.results_table = QTableWidget()
        self.layout.addWidget(self.results_table)

        # Menu Bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        # Import Action
        self.image_loader_dialog = ImageLoaderDialog()
        self.image_loader_dialog.cont_btn.clicked.connect(self._on_image_loaded)

        import_action = QAction("Import Results", self)
        import_action.triggered.connect(self.image_loader_dialog.load_image)
        # import_action.triggered.connect(self.show_image_loader)
        file_menu.addAction(import_action)

        self.tab = {}
        # Export Actions
        export_excel_a = QAction("Export to Excel", self)
        export_excel_a.triggered.connect(self.export_excel)
        # export_excel.triggered.connect(self.export_excel)
        file_menu.addAction(export_excel_a)

        export_pdf_a = QAction("Export to PDF", self)
        export_pdf_a.triggered.connect(self.export_pdf)
        # export_pdf.triggered.connect(self.export_pdf)
        file_menu.addAction(export_pdf_a)

        self.setCentralWidget(central_widget)
        self.show()

    def create_tables(self):
        cursor = self.conn.cursor()

        # Races table remains the same
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS races (
                id INTEGER PRIMARY KEY,
                class_name TEXT,
                date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(class_name, date_added)
            )
        """)

        # Participants table (now stores individual competitor info)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY,
                full_name TEXT UNIQUE
            )
        """)

        # Race Results (links participants to races with positions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS race_results (
                id INTEGER PRIMARY KEY,
                race_id INTEGER,
                participant_id INTEGER,
                position INTEGER,
                FOREIGN KEY(race_id) REFERENCES races(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                UNIQUE(race_id, participant_id)
            )
        """)
        self.conn.commit()

    def populate_classes(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT class_name FROM races")
        self.class_combo.clear()
        self.class_combo.addItems([row[0] for row in cursor.fetchall()])

    def build_table_result(self):
        cursor = self.conn.cursor()

        cursor.execute(
            "SELECT id, date_added FROM races WHERE class_name = (?)",
            (self.class_combo.currentText(),),
        )
        races = cursor.fetchall()
        race_ids, race_dates = list(zip(*races))
        # print(races)
        # print(race_dates)
        race_dates = [
            datetime.strptime(race_date, "%Y-%m-%d").strftime("%d.%m.%Y")
            for race_date in race_dates
        ]
        rid_to_tcol = dict(zip(race_ids, range(1, 1 + len(race_ids))))
        rid_to_rdate = dict(zip(race_ids, race_dates))
        # print(f"{rid_to_tcol = }")

        self.results_table.setColumnCount(2 + len(race_ids))
        self.results_table.setHorizontalHeaderLabels(
            [
                "Участник",
                *race_dates,
                "Итог",
            ]
        )

        placeholders = lambda what: f"({', '.join('?' for _ in what)})"
        # print(race_ids)

        cursor.execute(
            f"SELECT participant_id, race_id, position FROM race_results WHERE race_id IN {placeholders(race_ids)}",
            (*race_ids,),
        )
        data = cursor.fetchall()
        p_ids, race_ids, positions = list(zip(*data))
        pid_to_data = defaultdict(list)
        for p_id, race_id, pos in data:
            pid_to_data[p_id].append((race_id, pos))
        # pid_to_data = dict(zip(p_ids, zip(race_ids, positions)))
        # print(pid_to_data)
        p_ids = tuple(pid_to_data.keys())
        # print(len(p_ids), len(race_ids), len(positions))

        cursor.execute(
            f"SELECT DISTINCT id, full_name FROM participants WHERE id IN {placeholders(p_ids)}",
            (*p_ids,),
        )
        pid_to_name = dict(cursor.fetchall())
        # print(p_ids, positions)
        self.results_table.setRowCount(len(set(p_ids)))

        rating = [
            250,
            210,
            180,
            155,
            135,
            120,
            110,
            100,
            82,
            78,
            74,
            70,
            66,
            62,
            58,
            54,
            50,
            47,
            44,
            41,
            38,
            35,
            32,
            29,
        ]
        rating.extend(range(26, 0, -1))

        self.tab = pd.DataFrame(
            columns=["participant", *race_dates, "res"], index=p_ids
        )

        # self.tab = {}
        for i, (p_id, data) in enumerate(pid_to_data.items()):
            p_name = pid_to_name[p_id]
            self.tab.loc[p_id, "participant"] = p_name
            for race_id, pos in data:
                self.tab.loc[p_id, rid_to_rdate[race_id]] = rating[pos]
        self.tab = self.tab.fillna(0)
        self.tab["res"] = self.tab[[*race_dates]].sum(axis=1)

        self.tab = self.tab.sort_values(
            by=["res", "participant"], ascending=[False, False]
        )

        # breakpoint()
        # results = [(rid_to_tcol[race_id], rating[pos]) for race_id, pos in data]
        # gl_res = sum(rating[pos] for _, pos in data)

        # self.tab[p_id] = (p_name, results, gl_res)

        # gl_res_order = sorted(
        #     self.tab,
        #     key=lambda k: (lambda name, res, gl_res: (-gl_res, name))(*self.tab[k]),
        # )
        # breakpoint()

        for i, (index, row_data) in enumerate(self.tab.iterrows()):
            for j, col in enumerate(self.tab.columns):
                if row_data[col] == 0:
                    row_data[col] = ""
                self.results_table.setItem(i, j, QTableWidgetItem(str(row_data[col])))
            # self.results_table.setItem(i, 0, QTableWidgetItem(str(row_data["participant"])))
            # for rcol, score in results:
            #     self.results_table.setItem(i, rcol, QTableWidgetItem(str(score)))
            # self.results_table.setItem(
            #     i, self.results_table.columnCount() - 1, QTableWidgetItem(str(gl_res))
            # )

        # for i, p_id in enumerate(gl_res_order):
        #     p_name, results, gl_res = self.tab[p_id]
        # p_name = pid_to_name[p_id]
        # results = [(rid_to_tcol[race_id], rating[pos]) for race_id, pos in data]
        # gl_res = sum(rating[pos] for _, pos in data)

        # self.results_table.setItem(i, 0, QTableWidgetItem(str(p_name)))
        # for rcol, score in results:
        #     self.results_table.setItem(i, rcol, QTableWidgetItem(str(score)))
        # self.results_table.setItem(
        #     i, self.results_table.columnCount() - 1, QTableWidgetItem(str(gl_res))
        # )

        # for i, p_id in enumerate(pid_to_data, start=1):
        #     self.results_table.setItem(
        #         i - 1, 0, QTableWidgetItem(str(pid_to_name[p_id]))
        #     )
        #     print(pid_to_data[p_id])
        #     for race_id, pos in pid_to_data[p_id]:
        #         self.results_table.setItem(
        #             i - 1, rid_to_tcol[race_id], QTableWidgetItem(str(rating[pos]))
        #         )

        self.results_table.resizeColumnsToContents()

    def _on_image_loaded(self):
        race_typ, date, participants = self.image_loader_dialog.export_table()
        self.image_loader_dialog.close()

        cursor = self.conn.cursor()
        # print(f"{race_typ = }")
        # print(f"{date = }")

        # cursor.execute("select * from races")
        # res = cursor.fetchall()
        # print(res)

        # Insert or get race ID
        cursor.execute(
            """
            INSERT INTO races (class_name, date_added) VALUES (?, ?)
            ON CONFLICT(class_name, date_added)
            DO UPDATE SET
                class_name = excluded.class_name,
                date_added = excluded.date_added
            RETURNING id
            """,
            (
                race_typ,
                date.strftime("%Y-%m-%d"),
            ),
        )
        race_id = cursor.fetchone()[0]
        # print(race_id)

        for pos, participant in enumerate(participants, start=1):
            # Insert or get participant
            cursor.execute(
                """
                INSERT INTO participants (full_name) VALUES (?)
                ON CONFLICT(full_name) DO UPDATE SET full_name=full_name
                RETURNING id
            """,
                (participant,),
            )
            participant_id = cursor.fetchone()[0]
            # print(f"{participant_id = }")

            # print(race_id, f"{pos = }", participant, f"{participant_id = }")
            # Insert race result
            cursor.execute(
                """
                INSERT INTO race_results (race_id, participant_id, position)
                VALUES (?, ?, ?)
                ON CONFLICT(race_id, participant_id)
                DO UPDATE SET
                    race_id = excluded.race_id,
                    participant_id = excluded.participant_id,
                    position = excluded.position
            """,
                (
                    race_id,
                    participant_id,
                    pos,
                ),
            )
        self.conn.commit()

        # update the combobox items
        self.populate_classes()

    def export_excel(self):
        class_name = self.class_combo.currentText()
        if not class_name:
            return

        cols = self.tab.columns.to_list()
        _, *dates, _ = cols.copy()
        new_cols = ["Участник", *dates, "Итог"]
        new_cols = dict(zip(cols, new_cols))
        renamed_df = self.tab.rename(columns=new_cols)

        renamed_df.to_excel(f"{class_name}_results.xlsx", index=False)

    def export_pdf(self):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        class_name = self.class_combo.currentText()
        if not class_name:
            return

        cols = self.tab.columns.to_list()
        _, *dates, _ = cols.copy()
        new_cols = ["Участник", *dates, "Итог"]
        new_cols = dict(zip(cols, new_cols))
        renamed_df = self.tab.rename(columns=new_cols)

        document = SimpleDocTemplate(f"{class_name}_results.pdf", pagesize=letter)
        # Register a font that supports Cyrillic characters
        pdfmetrics.registerFont(TTFont("DejaVuSans", "Ubuntu-L.ttf"))

        # Create a list to hold the table elements
        elements = []

        # Convert DataFrame to a list of lists
        data_for_table = [renamed_df.columns.tolist()] + renamed_df.values.tolist()

        # Create a Table
        table = Table(data_for_table)

        # Add style to the table
        style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),  # Header background color
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),  # Header text color
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),  # Center align all cells
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),  # Header font
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),  # Padding for header
                (
                    "BACKGROUND",
                    (0, 1),
                    (-1, -1),
                    colors.beige,
                ),  # Background color for data rows
                ("GRID", (0, 0), (-1, -1), 1, colors.black),  # Grid lines
            ]
        )

        table.setStyle(style)

        # Add the table to the elements list
        elements.append(table)

        # Build the PDF
        document.build(elements)

        # pdf = canvas.Canvas(f"{class_name}_results.pdf", pagesize=pagesizes.A4)
        # pdf.setFont("Helvetica", 12)
        # y = 800
        # for row in cursor.fetchall():
        #     pdf.drawString(100, y, f"{row[1]}. {row[0]}")
        #     y -= 20
        #     if y < 50:
        #         pdf.showPage()
        #         y = 800
        # pdf.save()


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
        # self.table.setColumnCount(2)
        # self.table.setHorizontalHeaderLabels(["Name", "Position"])
        layout.addWidget(self.table, 50)

        # Buttons
        self.cont_btn = QPushButton("Continue")
        # self.cont_btn.clicked.connect(self.export_table)
        layout.addWidget(self.cont_btn)

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
        date = date.strftime("%d.%m.%Y") if not isinstance(date, str) else ""
        self._add_row(1, "Дата", date, conf)
        self._add_row(3, "Позиция", "Участник", "", show_color=False)

        for i, (participant, confidence) in enumerate(
            race_result.full_participants, start=4
        ):
            self._add_row(i, i - 3, participant, confidence)
            pos_item = self.table.item(i, 0)
            pos_item.setTextAlignment(Qt.AlignCenter)

        self.table.resizeColumnsToContents()

    def export_table(self):
        race_typ = self.table.item(0, 1).text()
        date = datetime.strptime(self.table.item(1, 1).text(), "%d.%m.%Y").date()
        participants = [
            self.table.item(i, 1).text() for i in range(4, self.table.rowCount())
        ]

        return race_typ, date, participants


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    sys.exit(app.exec())
