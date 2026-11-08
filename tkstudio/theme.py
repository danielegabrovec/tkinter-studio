"""Token visivi e icone vettoriali, senza risorse di rete."""
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

PALETTES = {
    "dark": dict(bg="#10151e", panel="#171e29", raised="#202a38", field="#111923", border="#2c394c", text="#e6edf7", muted="#a2b1c6", accent="#62dfbf", accent_dark="#113f38", selection="#234b4d", error="#ffa6ac"),
    "light": dict(bg="#e9edf3", panel="#ffffff", raised="#f1f4f8", field="#ffffff", border="#c6d0de", text="#1b2b40", muted="#51647d", accent="#087e68", accent_dark="#dcf6ee", selection="#d4eee7", error="#b32336"),
}


def stylesheet(theme="dark"):
    c = PALETTES[theme]
    return f"""
    QWidget {{ background: {c['panel']}; color: {c['text']}; font-family: 'Segoe UI'; font-size: 12px; }}
    QMainWindow, #workspace {{ background: {c['bg']}; }}
    #header {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
    #brand {{ font-size: 17px; font-weight: 700; letter-spacing: -0.3px; }}
    #projectLabel {{ color: {c['muted']}; font-size: 12px; }}
    #sectionTitle {{ color: {c['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1px; background: transparent; }}
    #sectionHeading {{ font-size: 14px; font-weight: 600; }}
    #muted, #hint {{ color: {c['muted']}; background: transparent; }}
    #hint {{ font-size: 11px; }}
    #eyebrow {{ color: {c['accent']}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
    #syncBadge {{ color: {c['accent']}; background: {c['accent_dark']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 4px 8px; font-size: 10px; }}
    #syncNotice {{ background: {c['raised']}; border-bottom: 1px solid {c['border']}; color: {c['error']}; padding: 8px 12px; }}
    #editorToolbar {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
    QPushButton, QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 6px 9px; min-height: 20px; }}
    QPushButton:hover, QToolButton:hover {{ background: {c['raised']}; border-color: {c['border']}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {c['selection']}; }}
    QPushButton:focus, QToolButton:focus {{ border-color: {c['accent']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {c['muted']}; }}
    QToolButton:checked {{ background: {c['selection']}; color: {c['accent']}; border-color: {c['border']}; }}
    #primaryButton {{ background: {c['accent']}; color: {'#102b25' if theme == 'dark' else '#ffffff'}; font-weight: 700; padding: 7px 18px; }}
    #primaryButton:hover {{ background: {'#83ebd0' if theme == 'dark' else '#096b59'}; }}
    #primaryButton:disabled {{ background: {c['raised']}; color: {c['muted']}; }}
    #secondaryButton {{ border: 1px solid {c['border']}; background: {c['raised']}; }}
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 5px 7px; selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
    QPlainTextEdit, QTextEdit {{ border-radius: 0px; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; selection-background-color: {c['selection']}; border: 1px solid {c['border']}; }}
    QTreeView, QListWidget, QTreeWidget {{ background: {c['panel']}; border: none; outline: none; selection-background-color: {c['selection']}; show-decoration-selected: 1; }}
    QTreeView::item, QTreeWidget::item {{ height: 28px; border-radius: 3px; }}
    QListWidget::item {{ min-height: 32px; padding: 3px 7px; border: 1px solid transparent; border-radius: 4px; }}
    QListWidget::item:hover, QTreeView::item:hover {{ background: {c['raised']}; }}
    QListWidget::item:selected, QTreeView::item:selected, QTreeWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
    QHeaderView::section {{ background: {c['raised']}; color: {c['muted']}; border: none; padding: 6px; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {c['border']}; }}
    QTabBar {{ background: {c['panel']}; }}
    QTabBar::tab {{ color: {c['muted']}; background: {c['panel']}; padding: 9px 12px; border-bottom: 2px solid transparent; min-width: 55px; }}
    QTabBar::tab:selected {{ color: {c['text']}; background: {c['raised']}; border-bottom: 2px solid {c['accent']}; }}
    QTabBar::tab:hover {{ background: {c['raised']}; }}
    QSplitter::handle {{ background: {c['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QScrollArea {{ background: {c['panel']}; border: none; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; margin: 0; }}
    QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 0; }}
    QScrollBar::handle {{ background: {c['border']}; border-radius: 4px; min-height: 26px; min-width: 26px; }}
    QScrollBar::handle:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QStatusBar {{ background: {c['panel']}; color: {c['muted']}; border-top: 1px solid {c['border']}; font-size: 11px; }}
    QStatusBar::item {{ border: none; }}
    QMenuBar {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
    QMenuBar::item {{ padding: 5px 9px; background: transparent; }}
    QMenuBar::item:selected, QMenu::item:selected {{ background: {c['selection']}; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 5px; }}
    QMenu::item {{ padding: 7px 24px 7px 12px; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px; }}
    QToolTip {{ background: {c['raised']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
    QCheckBox {{ spacing: 7px; background: transparent; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {c['muted']}; border-radius: 3px; background: {c['field']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 5px; margin-top: 12px; padding-top: 12px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 9px; padding: 0 4px; color: {c['muted']}; }}
    QDialogButtonBox {{ background: transparent; }}
    """


def icon(name, color="#a2b1c6", size=20):
    """Piccole icone originali disegnate su una griglia 24×24."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24)
    p.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name == "play":
        p.setBrush(QColor(color)); p.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(19, 12), QPointF(8, 19)]))
    elif name == "stop":
        p.setBrush(QColor(color)); p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif name == "folder":
        path = QPainterPath(); path.moveTo(3, 7); path.lineTo(3, 19); path.lineTo(21, 19); path.lineTo(21, 7); path.lineTo(12, 7); path.lineTo(10, 4); path.lineTo(3, 4); path.closeSubpath(); p.drawPath(path)
    elif name == "save":
        p.drawRoundedRect(QRectF(4, 3, 16, 18), 2, 2); p.drawRect(QRectF(8, 3, 8, 6)); p.drawRect(QRectF(8, 14, 8, 7))
    elif name in ("plus", "add"):
        p.drawLine(12, 5, 12, 19); p.drawLine(5, 12, 19, 12)
    elif name == "code":
        p.drawPolyline(QPolygonF([QPointF(8, 6), QPointF(2, 12), QPointF(8, 18)])); p.drawPolyline(QPolygonF([QPointF(16, 6), QPointF(22, 12), QPointF(16, 18)])); p.drawLine(14, 4, 10, 20)
    elif name == "split":
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2); p.drawLine(12, 4, 12, 20)
    elif name in ("designer", "frame", "app"):
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2); p.drawLine(3, 9, 21, 9); p.drawLine(7, 6, 7, 6); p.drawLine(10, 6, 10, 6)
        if name == "app":
            p.setBrush(QColor(color)); p.drawRoundedRect(QRectF(7, 12, 5, 5), 1, 1); p.setBrush(Qt.BrushStyle.NoBrush); p.drawLine(15, 13, 18, 13); p.drawLine(15, 16, 18, 16)
    elif name == "search":
        p.drawEllipse(QRectF(4, 3, 12, 12)); p.drawLine(14, 14, 21, 21)
    elif name == "sun":
        p.drawEllipse(QRectF(8, 8, 8, 8))
        for a, b, c, d in [(12, 2, 12, 4), (12, 20, 12, 22), (2, 12, 4, 12), (20, 12, 22, 12), (5, 5, 6, 6), (18, 18, 19, 19), (5, 19, 6, 18), (18, 6, 19, 5)]: p.drawLine(a, b, c, d)
    elif name == "trash":
        p.drawLine(5, 7, 19, 7); p.drawLine(9, 4, 15, 4); p.drawPolyline(QPolygonF([QPointF(7, 7), QPointF(8, 21), QPointF(16, 21), QPointF(17, 7)])); p.drawLine(11, 11, 11, 17); p.drawLine(14, 11, 14, 17)
    elif name == "label":
        p.drawLine(5, 5, 19, 5); p.drawLine(12, 5, 12, 20); p.drawLine(9, 20, 15, 20)
    elif name == "check":
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 3, 3); p.drawPolyline(QPolygonF([QPointF(8, 12), QPointF(11, 15), QPointF(17, 9)]))
    elif name == "radio":
        p.drawEllipse(QRectF(4, 4, 16, 16)); p.setBrush(QColor(color)); p.drawEllipse(QRectF(9, 9, 6, 6))
    elif name == "slider":
        p.drawLine(3, 12, 21, 12); p.setBrush(QColor(color)); p.drawEllipse(QRectF(8, 8, 8, 8))
    elif name in ("entry", "button"):
        p.drawRoundedRect(QRectF(2, 6, 20, 12), 3, 3)
        if name == "entry": p.drawLine(6, 9, 6, 15)
        else: p.drawLine(9, 12, 15, 12)
    elif name == "list":
        for y in (6, 12, 18): p.drawLine(4, y, 5, y); p.drawLine(9, y, 21, y)
    elif name == "file":
        path = QPainterPath(); path.moveTo(5, 2); path.lineTo(14, 2); path.lineTo(20, 8); path.lineTo(20, 22); path.lineTo(5, 22); path.closeSubpath(); p.drawPath(path); p.drawLine(14, 2, 14, 8); p.drawLine(14, 8, 20, 8)
    elif name in ("undo", "redo"):
        if name == "redo": p.translate(24, 0); p.scale(-1, 1)
        p.drawPolyline(QPolygonF([QPointF(8, 4), QPointF(3, 9), QPointF(8, 14)])); p.drawLine(3, 9, 15, 9); p.drawArc(QRectF(10, 9, 10, 10), -90 * 16, 180 * 16)
    elif name == "info":
        p.drawEllipse(QRectF(3, 3, 18, 18)); p.drawLine(12, 10, 12, 17); p.drawPoint(12, 7)
    else:
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 3, 3); p.drawLine(8, 9, 16, 9); p.drawLine(8, 13, 16, 13)
    p.end()
    return QIcon(pm)


def widget_icon(kind, color="#a2b1c6"):
    short = kind.rsplit(".", 1)[-1]
    name = {"Frame": "frame", "LabelFrame": "frame", "Label": "label", "Button": "button", "Entry": "entry", "Text": "code", "Checkbutton": "check", "Radiobutton": "radio", "Scale": "slider", "Progressbar": "slider", "Listbox": "list", "Treeview": "list", "Combobox": "entry", "Spinbox": "entry"}.get(short, "frame")
    return icon(name, color)
