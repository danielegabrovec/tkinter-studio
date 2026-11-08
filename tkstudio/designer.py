"""A native, non-executing canvas for designing Tkinter interfaces.

All coordinates are logical pixels relative to the widget's Tk parent.  The
canvas deliberately paints representations of controls: the Run command opens
the real Tk application in its own process.
"""
from __future__ import annotations

import copy
import uuid

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QComboBox, QGraphicsItem, QGraphicsObject, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QMenu,
    QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from .model import UiDocument, WidgetNode, WIDGET_SPECS, create_widget


WIDGET_MIME = "application/x-tkstudio-widget"
ACCENT = QColor("#15ad91")
SELECTION = QColor("#087fdb")
HANDLE = 7.0
GRID = 8


def _button(text: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setAutoRaise(True)
    button.setMinimumHeight(30)
    return button


def _is_container(node: WidgetNode) -> bool:
    spec = WIDGET_SPECS.get(node.kind)
    return bool(spec and getattr(spec, "container", False))


def _font(size=13, bold=False) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(size)
    font.setBold(bold)
    return font


class ArtboardItem(QGraphicsRectItem):
    def __init__(self, document: UiDocument, view: "DesignerView"):
        super().__init__(0, 0, document.width, document.height)
        self.document = document
        self.view = view
        self.setZValue(-10)
        self.setPen(QPen(QColor("#526175"), 1))

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 28))
        painter.drawRoundedRect(rect.adjusted(-4, -4, 6, 7), 4, 4)
        background = QColor(self.document.background)
        if not background.isValid():
            background = QColor("#f4f6fb")
        painter.setBrush(background)
        painter.setPen(QPen(QColor("#63758b"), 1))
        painter.drawRect(rect)
        if self.view.grid_enabled:
            # Draw at useful visual density even at a small zoom level.
            step = GRID if self.view.zoom >= 0.65 else GRID * 2
            painter.setPen(QPen(QColor(87, 105, 129, 44), 1))
            for x in range(step, self.document.width, step):
                for y in range(step, self.document.height, step):
                    painter.drawPoint(QPointF(x, y))
        painter.setFont(_font(12))
        painter.setPen(QColor("#a2aebe") if self.view.theme == "dark" else QColor("#53647b"))
        painter.drawText(QRectF(1, -30, rect.width(), 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.document.title)
        painter.drawText(QRectF(0, rect.height() + 12, rect.width(), 20),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         f"{self.document.width} × {self.document.height} px")
        if not self.document.widgets:
            painter.setFont(_font(19, True))
            painter.setPen(QColor("#78869a"))
            painter.drawText(rect.adjusted(32, 20, -32, -20), Qt.AlignmentFlag.AlignCenter,
                             "La tua interfaccia inizia qui\n\nTrascina un componente dalla libreria")

    def boundingRect(self):
        return self.rect().adjusted(-8, -34, 8, 38)


class WidgetItem(QGraphicsObject):
    """A selectable control with native canvas drag and eight resize handles."""

    def __init__(self, node: WidgetNode, view: "DesignerView", parent=None):
        super().__init__(parent)
        self.node = node
        self.view = view
        self._resize_handle = ""
        self._resize_origin = None
        self._press_scene = QPointF()
        self._dirty = False
        self._handles_visible = False
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setPos(node.x, node.y)
        label = WIDGET_SPECS[node.kind].label if node.kind in WIDGET_SPECS else node.kind
        self.setToolTip(f"{node.name} · {label}\n{node.width} × {node.height} px\nDoppio clic: modifica evento o codice")

    def boundingRect(self):
        return QRectF(-5, -5, self.node.width + 10, self.node.height + 10)

    def shape(self):
        path = QPainterPath()
        path.addRect(QRectF(-3, -3, self.node.width + 6, self.node.height + 6))
        return path

    def _handles(self):
        w, h = self.node.width, self.node.height
        return {
            "nw": QPointF(0, 0), "n": QPointF(w / 2, 0), "ne": QPointF(w, 0),
            "w": QPointF(0, h / 2), "e": QPointF(w, h / 2),
            "sw": QPointF(0, h), "s": QPointF(w / 2, h), "se": QPointF(w, h),
        }

    def _handle_at(self, point):
        if not self.isSelected():
            return ""
        tolerance = max(5.5, 5.5 / self.view.zoom)
        for name, center in self._handles().items():
            if abs(point.x() - center.x()) <= tolerance and abs(point.y() - center.y()) <= tolerance:
                return name
        return ""

    def _parent_size(self):
        parent = self.view.document.find(self.node.parent) if self.node.parent else None
        return (parent.width, parent.height) if parent else (self.view.document.width, self.view.document.height)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and not self.view._building:
            if self._resize_handle:
                return value
            w, h = self._parent_size()
            x, y = value.x(), value.y()
            if self.view.snap_enabled:
                x, y = round(x / GRID) * GRID, round(y / GRID) * GRID
            return QPointF(max(0, min(x, max(0, w - self.node.width))),
                           max(0, min(y, max(0, h - self.node.height))))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self.view._building:
            self.node.x = round(self.pos().x())
            self.node.y = round(self.pos().y())
            self.view.panel._update_footer()
        return super().itemChange(change, value)

    def hoverMoveEvent(self, event):
        handle = self._handle_at(event.pos()) if self.view.editable else ""
        cursors = {
            "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
            "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
            "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
        }
        self.setCursor(cursors.get(handle, Qt.CursorShape.SizeAllCursor if self.view.editable else Qt.CursorShape.ArrowCursor))
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if not self.view.editable or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        was_selected = self.isSelected()
        self.view.begin_gesture()
        handle = self._handle_at(event.pos())
        if handle:
            self._resize_handle = handle
            self._resize_origin = (self.node.x, self.node.y, self.node.width, self.node.height)
            self._press_scene = event.scenePos()
            self.view._selection_changed()
            event.accept()
            return
        super().mousePressEvent(event)
        if was_selected:
            # Qt emits no selectionChanged when an already selected control is
            # clicked again. Repoint its source while the button is held, so the
            # coordinator can defer layout changes until after a drag/double click.
            self.view._selection_changed()

    def mouseMoveEvent(self, event):
        if not self.view.editable:
            event.accept()
            return
        if not self._resize_handle or self._resize_origin is None:
            super().mouseMoveEvent(event)
            return
        origin_x, origin_y, origin_w, origin_h = self._resize_origin
        delta = event.scenePos() - self._press_scene
        dx, dy = delta.x(), delta.y()
        if self.view.snap_enabled:
            dx, dy = round(dx / GRID) * GRID, round(dy / GRID) * GRID
        left, top, right, bottom = origin_x, origin_y, origin_x + origin_w, origin_y + origin_h
        handle = self._resize_handle
        pw, ph = self._parent_size()
        child_right = max((child.x + child.width for child in self.view.document.widgets if child.parent == self.node.id), default=24)
        child_bottom = max((child.y + child.height for child in self.view.document.widgets if child.parent == self.node.id), default=20)
        min_w, min_h = max(24, child_right), max(20, child_bottom)
        if "w" in handle:
            left = max(0, min(origin_x + dx, right - min_w))
        if "e" in handle:
            right = min(pw, max(origin_x + origin_w + dx, left + min_w))
        if "n" in handle:
            top = max(0, min(origin_y + dy, bottom - min_h))
        if "s" in handle:
            bottom = min(ph, max(origin_y + origin_h + dy, top + min_h))
        self.prepareGeometryChange()
        self.node.x, self.node.y = round(left), round(top)
        self.node.width, self.node.height = max(24, round(right - left)), max(20, round(bottom - top))
        self.setPos(self.node.x, self.node.y)
        self.update()
        self.view.panel._update_footer()
        event.accept()

    def mouseReleaseEvent(self, event):
        resizing = bool(self._resize_handle)
        self._resize_handle = ""
        self._resize_origin = None
        if not resizing:
            super().mouseReleaseEvent(event)
        else:
            event.accept()
        self.view.end_gesture()

    def mouseDoubleClickEvent(self, event):
        if self.view.editable:
            self.view.panel.widget_activated.emit(self.node.id)
        event.accept()

    def contextMenuEvent(self, event):
        if not self.view.editable:
            return
        if not self.isSelected():
            self.view.scene().clearSelection()
            self.setSelected(True)
        menu = QMenu()
        duplicate = menu.addAction("Duplica\tCtrl+D")
        delete = menu.addAction("Elimina\tCanc")
        menu.addSeparator()
        code = menu.addAction("Vai al codice")
        result = menu.exec(event.screenPos())
        if result is duplicate:
            self.view.panel.duplicate_selected()
        elif result is delete:
            self.view.panel.delete_selected()
        elif result is code:
            self.view.panel.widget_activated.emit(self.node.id)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.node.width, self.node.height)
        p = self.node.properties
        kind = self.node.kind.split(".")[-1]
        text = str(p.get("text", self.node.name))
        style_name = str(p.get("style", ""))
        painter.setFont(_font())
        if style_name == "Hero.TLabel":
            painter.setFont(_font(27, True))
        elif style_name == "Accent.TButton":
            painter.setFont(_font(13, True))
        font_value = p.get("font")
        if isinstance(font_value, (list, tuple)) and len(font_value) >= 2:
            custom = QFont(str(font_value[0]))
            try:
                custom.setPixelSize(max(8, abs(int(font_value[1])) * 4 // 3))
            except (ValueError, TypeError):
                custom.setPixelSize(13)
            if len(font_value) > 2:
                custom.setBold("bold" in str(font_value[2]))
            painter.setFont(custom)
        fg = QColor(str(p.get("foreground", p.get("fg", "#263549"))))
        if style_name == "Muted.TLabel":
            fg = QColor("#67748c")
        elif style_name == "Accent.TButton":
            fg = QColor("#ffffff")
        if not fg.isValid():
            fg = QColor("#263549")
        disabled = p.get("state") == "disabled"
        if disabled:
            fg = QColor("#8b96a5")
        border = QColor("#b6c2d1")
        fill = QColor("#ffffff")
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)

        if kind in ("Frame", "LabelFrame"):
            default_bg = "#ffffff" if style_name.startswith("Card.") else "#f8fafc"
            frame_bg = QColor(str(p.get("background", p.get("bg", default_bg))))
            painter.setBrush(frame_bg if frame_bg.isValid() else QColor("#f8fafc"))
            painter.setPen(QPen(QColor("#c9d3df"), 1, Qt.PenStyle.SolidLine))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            if kind == "LabelFrame":
                painter.setFont(_font(12, True))
                fm = painter.fontMetrics()
                title_rect = QRectF(12, -1, min(fm.horizontalAdvance(text) + 14, rect.width() - 18), 20)
                painter.fillRect(title_rect, frame_bg)
                painter.setPen(fg)
                painter.drawText(title_rect.adjusted(5, 0, -3, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            elif self.isSelected():
                painter.setPen(QColor("#91a0b2"))
                painter.setFont(_font(10))
                painter.drawText(rect.adjusted(7, 4, -7, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.node.name)
        elif kind == "Label":
            painter.setPen(fg)
            anchor = str(p.get("anchor", "w"))
            align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignCenter if anchor == "center" else Qt.AlignmentFlag.AlignRight if "e" in anchor else Qt.AlignmentFlag.AlignLeft)
            painter.drawText(rect.adjusted(2, 0, -2, 0), align, text)
        elif kind == "Button":
            if style_name == "Accent.TButton" and not disabled:
                painter.setBrush(QColor("#5267db"))
                painter.setPen(QPen(QColor("#5267db"), 1))
            else:
                painter.setBrush(QColor("#eef4fa") if not disabled else QColor("#f0f2f5"))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            painter.setPen(fg)
            painter.drawText(rect.adjusted(7, 2, -7, -2), Qt.AlignmentFlag.AlignCenter, text)
        elif kind in ("Entry", "Combobox", "Spinbox"):
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            painter.setPen(QPen(QColor("#8397b0"), 1.2))
            painter.drawLine(QPointF(3, rect.height() - 1), QPointF(rect.width() - 3, rect.height() - 1))
            if kind == "Combobox":
                values = p.get("values", [])
                if "text" not in p:
                    text = str(values[0]) if values else ""
                self._chevron(painter, rect.width() - 13, rect.height() / 2)
            elif kind == "Spinbox":
                if "text" not in p:
                    text = str(p.get("from_", 0))
                painter.setPen(QPen(border, 1))
                painter.drawLine(QPointF(rect.width() - 23, 1), QPointF(rect.width() - 23, rect.height() - 1))
                painter.drawLine(QPointF(rect.width() - 23, rect.height() / 2), QPointF(rect.width() - 1, rect.height() / 2))
                self._chevron(painter, rect.width() - 12, rect.height() * .74)
                self._chevron(painter, rect.width() - 12, rect.height() * .25, up=True)
            else:
                text = str(p.get("text", ""))
                if p.get("show"):
                    text = str(p["show"]) * len(text)
            painter.setPen(fg)
            painter.drawText(rect.adjusted(9, 2, -28 if kind != "Entry" else -8, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        elif kind in ("Checkbutton", "Radiobutton"):
            size = min(16, rect.height() - 4)
            control = QRectF(2, (rect.height() - size) / 2, size, size)
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(QColor("#8294aa"), 1.2))
            if kind == "Checkbutton":
                painter.drawRoundedRect(control, 2, 2)
            else:
                painter.drawEllipse(control)
            selected = bool(p.get("selected", False))
            if selected:
                painter.setPen(QPen(ACCENT, 2))
                if kind == "Checkbutton":
                    painter.drawLine(QPointF(control.left() + 3, control.center().y()), QPointF(control.left() + 6, control.bottom() - 4))
                    painter.drawLine(QPointF(control.left() + 6, control.bottom() - 4), QPointF(control.right() - 2, control.top() + 3))
                else:
                    painter.setBrush(ACCENT)
                    painter.drawEllipse(control.adjusted(4, 4, -4, -4))
            painter.setPen(fg)
            painter.drawText(rect.adjusted(size + 10, 1, -2, -1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        elif kind == "Text":
            painter.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 3, 3)
            painter.setPen(fg)
            painter.drawText(rect.adjusted(9, 8, -9, -8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, str(p.get("text", "")))
        elif kind == "Listbox":
            painter.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 3, 3)
            items = p.get("items", ["Elemento 1", "Elemento 2", "Elemento 3"])
            painter.setPen(fg)
            for i, item in enumerate(items if isinstance(items, list) else str(items).splitlines()):
                if i * 25 + 12 > rect.height():
                    break
                if i == 0:
                    painter.fillRect(QRectF(3, 3, rect.width() - 6, 25), QColor("#e9f4fd"))
                painter.drawText(QRectF(10, 4 + i * 25, rect.width() - 20, 25), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(item))
        elif kind == "Treeview":
            painter.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 3, 3)
            painter.fillRect(QRectF(1, 1, rect.width() - 2, 28), QColor("#edf1f6"))
            values = p.get("columns", ["Colonna 1", "Colonna 2"])
            columns = list(values) if isinstance(values, (list, tuple)) and values else ["Elemento", "Valore"]
            col_width = rect.width() / len(columns)
            painter.setFont(_font(11, True))
            painter.setPen(fg)
            for i, column in enumerate(columns):
                painter.drawText(QRectF(i * col_width + 10, 1, col_width - 15, 27), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(column))
            painter.setPen(QPen(QColor("#edf1f6"), 1))
            for y in range(56, int(rect.height()), 28):
                painter.drawLine(QPointF(1, y), QPointF(rect.width() - 1, y))
        elif kind == "Progressbar":
            vertical = p.get("orient") == "vertical"
            painter.setBrush(QColor("#dfe6ee"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(0, 3, 0, -3) if not vertical else rect.adjusted(3, 0, -3, 0), 3, 3)
            try:
                value = max(0, min(1, float(p.get("value", 45)) / max(1, float(p.get("maximum", 100)))))
            except (TypeError, ValueError):
                value = .45
            painter.setBrush(ACCENT)
            fillrect = QRectF(3, rect.height() * (1 - value), rect.width() - 6, rect.height() * value) if vertical else QRectF(0, 3, rect.width() * value, rect.height() - 6)
            painter.drawRoundedRect(fillrect, 3, 3)
        elif kind == "Scale":
            vertical = p.get("orient") == "vertical"
            painter.setPen(QPen(QColor("#c9d5e1"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if vertical:
                painter.drawLine(QPointF(rect.width() / 2, 8), QPointF(rect.width() / 2, rect.height() - 8))
                center = QPointF(rect.width() / 2, rect.height() * .45)
            else:
                painter.drawLine(QPointF(8, rect.height() / 2), QPointF(rect.width() - 8, rect.height() / 2))
                center = QPointF(rect.width() * .45, rect.height() / 2)
            painter.setPen(QPen(ACCENT, 2))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(center, 7, 7)
        elif kind == "Separator":
            painter.setPen(QPen(QColor("#bac7d5"), 1))
            if p.get("orient") == "vertical":
                painter.drawLine(QPointF(rect.width() / 2, 0), QPointF(rect.width() / 2, rect.height()))
            else:
                painter.drawLine(QPointF(0, rect.height() / 2), QPointF(rect.width(), rect.height() / 2))
        elif kind == "Canvas":
            bg = QColor(str(p.get("background", p.get("bg", "#ffffff"))))
            painter.setBrush(bg if bg.isValid() else fill)
            painter.drawRect(rect.adjusted(.5, .5, -.5, -.5))
            painter.setPen(QColor("#96a3b3"))
            painter.setFont(_font(11))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Canvas")
        else:
            painter.drawRect(rect)
            painter.setPen(fg)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        if self.isSelected():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(SELECTION, 1.5)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(rect)
            if self.view.editable:
                painter.setBrush(QColor("#ffffff"))
                size = max(5, HANDLE / self.view.zoom)
                for point in self._handles().values():
                    painter.drawRect(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))

    @staticmethod
    def _chevron(painter, x, y, up=False):
        painter.setPen(QPen(QColor("#64748b"), 1.3))
        direction = -1 if up else 1
        painter.drawLine(QPointF(x - 3, y - direction * 1.5), QPointF(x, y + direction * 1.5))
        painter.drawLine(QPointF(x, y + direction * 1.5), QPointF(x + 3, y - direction * 1.5))


class DesignerView(QGraphicsView):
    def __init__(self, panel: "DesignerPanel"):
        super().__init__(panel)
        self.panel = panel
        self.document = None
        self.items_by_id: dict[str, WidgetItem] = {}
        self.artboard = None
        self._building = False
        self._before_gesture = None
        self.editable = True
        self.grid_enabled = True
        self.snap_enabled = True
        self.zoom = 1.0
        self.theme = "dark"
        self._panning = False
        self._last_pan = None
        self.setScene(QGraphicsScene(self))
        self.setObjectName("designerCanvas")
        self.setAccessibleName("Designer visuale dell'interfaccia Tkinter")
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.ContainsItemShape)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.scene().selectionChanged.connect(self._selection_changed)
        self.set_theme("dark")

    def set_theme(self, theme):
        self.theme = theme
        self.setBackgroundBrush(QColor("#141d2a" if theme == "dark" else "#e8edf4"))
        # A palette change can otherwise repaint the artboard alone and leave
        # children absent from the next backing-store frame on Windows.
        self.scene().update()
        self.viewport().update()
        if self.artboard:
            self.artboard.update()

    def rebuild(self, document, selected_ids=None):
        self._building = True
        self.scene().blockSignals(True)
        self.document = document
        self.items_by_id.clear()
        self.scene().clear()
        self.artboard = ArtboardItem(document, self)
        self.scene().addItem(self.artboard)
        pending = list(document.widgets)
        while pending:
            progressed = False
            for node in pending[:]:
                if node.parent and node.parent not in self.items_by_id:
                    continue
                parent = self.items_by_id.get(node.parent, self.artboard)
                item = WidgetItem(node, self, parent)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.editable)
                self.items_by_id[node.id] = item
                pending.remove(node)
                progressed = True
            if not progressed:
                # The core validates parents; this avoids a UI freeze if a caller
                # supplies a malformed document while reporting an error.
                break
        for node_id in selected_ids or []:
            if node_id in self.items_by_id:
                self.items_by_id[node_id].setSelected(True)
        self.scene().setSceneRect(-120, -90, document.width + 240, document.height + 190)
        self.scene().blockSignals(False)
        self._building = False
        self.viewport().update()
        self._selection_changed()

    def _selection_changed(self):
        if self._building:
            return
        ids = self.panel.selected_ids()
        self.panel._update_footer()
        self.panel.selection_changed.emit(ids[0] if ids else None)

    def begin_gesture(self):
        if self._before_gesture is None and self.document is not None:
            self._before_gesture = copy.deepcopy(self.document.to_dict())

    def end_gesture(self):
        before, self._before_gesture = self._before_gesture, None
        if before is not None and before != self.document.to_dict():
            self.panel.document_changed.emit()

    def container_at(self, position, excluding=None):
        for item in self.scene().items(position):
            if isinstance(item, WidgetItem) and item.node.id not in (excluding or []) and _is_container(item.node):
                return item
        return None

    def dragEnterEvent(self, event):
        if self.editable and event.mimeData().hasFormat(WIDGET_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.editable and event.mimeData().hasFormat(WIDGET_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self.editable or not event.mimeData().hasFormat(WIDGET_MIME):
            event.ignore()
            return
        kind = bytes(event.mimeData().data(WIDGET_MIME)).decode("utf-8", errors="replace")
        if kind not in WIDGET_SPECS:
            event.ignore()
            return
        point = self.mapToScene(event.position().toPoint())
        if not self.artboard.rect().contains(point):
            event.ignore()
            return
        container = self.container_at(point)
        local = container.mapFromScene(point) if container else point
        self.panel.add_widget(kind, local, container.node.id if container else None)
        event.acceptProposedAction()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.panel._set_zoom(self.zoom * (1.1 if event.angleDelta().y() > 0 else 1 / 1.1))
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._last_pan = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if not self.editable and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._last_pan
            self._last_pan = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.end_gesture()

    def keyPressEvent(self, event: QKeyEvent):
        if not self.editable:
            super().keyPressEvent(event)
            return
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.panel.delete_selected()
            event.accept()
            return
        if ctrl and event.key() == Qt.Key.Key_D:
            self.panel.duplicate_selected()
            event.accept()
            return
        if ctrl and event.key() == Qt.Key.Key_A:
            for item in self.items_by_id.values():
                item.setSelected(True)
            event.accept()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in arrows and self.panel.selected_ids():
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = arrows[event.key()]
            self.begin_gesture()
            ids = self.panel.selected_ids()
            previous_snap = self.snap_enabled
            self.snap_enabled = False
            for node in self.panel._selected_roots(set(ids)):
                item = self.items_by_id[node.id]
                item.setPos(item.pos() + QPointF(dx * step, dy * step))
            self.snap_enabled = previous_snap
            self.end_gesture()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.scene().clearSelection()
            event.accept()
            return
        super().keyPressEvent(event)


class DesignerPanel(QWidget):
    selection_changed = pyqtSignal(object)
    document_changed = pyqtSignal()
    widget_activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document: UiDocument | None = None
        self.setObjectName("designerPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tools = QWidget()
        tools.setObjectName("canvasToolbar")
        toolbar = QHBoxLayout(tools)
        toolbar.setContentsMargins(14, 7, 14, 7)
        toolbar.setSpacing(8)
        label = QLabel("AREA DI LAVORO")
        label.setObjectName("eyebrow")
        toolbar.addWidget(label)
        toolbar.addStretch()
        self.grid_button = _button("Griglia", "Mostra o nascondi la griglia")
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        self.grid_button.toggled.connect(self.toggle_grid)
        toolbar.addWidget(self.grid_button)
        self.snap_button = _button("Aggancia", "Aggancia i componenti alla griglia di 8 pixel")
        self.snap_button.setCheckable(True)
        self.snap_button.setChecked(True)
        self.snap_button.toggled.connect(self.toggle_snap)
        toolbar.addWidget(self.snap_button)
        toolbar.addSpacing(5)
        minus = _button("−", "Riduci zoom · Ctrl + rotellina")
        minus.clicked.connect(self.zoom_out)
        toolbar.addWidget(minus)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setAccessibleName("Livello di zoom del designer")
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setFixedWidth(80)
        self.zoom_combo.addItems(["50%", "75%", "100%", "125%", "150%", "200%"])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.activated.connect(self._combo_zoom)
        self.zoom_combo.lineEdit().editingFinished.connect(self._combo_zoom)
        toolbar.addWidget(self.zoom_combo)
        plus = _button("+", "Aumenta zoom · Ctrl + rotellina")
        plus.clicked.connect(self.zoom_in)
        toolbar.addWidget(plus)
        fit_button = _button("Adatta", "Adatta l'intera finestra allo spazio disponibile")
        fit_button.clicked.connect(self.fit)
        toolbar.addWidget(fit_button)
        layout.addWidget(tools)
        self.view = DesignerView(self)
        layout.addWidget(self.view, 1)
        footer = QWidget()
        footer.setObjectName("canvasFooter")
        foot_layout = QHBoxLayout(footer)
        foot_layout.setContentsMargins(14, 7, 14, 7)
        self.selection_label = QLabel("Nessun elemento selezionato")
        self.selection_label.setObjectName("mutedLabel")
        foot_layout.addWidget(self.selection_label)
        foot_layout.addStretch()
        self.hint_label = QLabel("Trascina · Ridimensiona · Doppio clic per il codice")
        self.hint_label.setObjectName("mutedLabel")
        foot_layout.addWidget(self.hint_label)
        layout.addWidget(footer)

    @property
    def grid_enabled(self):
        return self.view.grid_enabled

    @property
    def snap_enabled(self):
        return self.view.snap_enabled

    def set_document(self, document):
        self.document = document
        self.view.rebuild(document)

    def refresh(self, selected_id=None):
        if self.document is None:
            return
        ids = [selected_id] if selected_id else self.selected_ids()
        self.view.rebuild(self.document, ids)

    def selected_ids(self):
        return [item.node.id for item in self.view.scene().selectedItems() if isinstance(item, WidgetItem)]

    def _selected_roots(self, ids):
        """Do not operate twice on a selected descendant of a selected item."""
        roots = []
        for node in self.document.widgets:
            if node.id not in ids:
                continue
            parent_id = node.parent
            seen = set()
            while parent_id and parent_id not in seen:
                if parent_id in ids:
                    break
                seen.add(parent_id)
                parent = self.document.find(parent_id)
                parent_id = parent.parent if parent else None
            else:
                roots.append(node)
        return roots

    def select_widget(self, node_id):
        self.view.scene().blockSignals(True)
        self.view.scene().clearSelection()
        item = self.view.items_by_id.get(node_id)
        if item:
            item.setSelected(True)
            self.view.ensureVisible(item, 30, 30)
        self.view.scene().blockSignals(False)
        self.view._selection_changed()

    def add_widget(self, kind, position=None, parent=None):
        if self.document is None or not self.view.editable or kind not in WIDGET_SPECS:
            return None
        if parent is None and position is None:
            selected = self.selected_ids()
            candidate = self.document.find(selected[0]) if selected else None
            if candidate and _is_container(candidate):
                parent = candidate.id
        if parent is not None:
            node_parent = self.document.find(parent)
            if not node_parent or not _is_container(node_parent):
                parent = None
        if position is None:
            siblings = [node for node in self.document.widgets if node.parent == parent]
            offset = len(siblings) % 7 * 16
            x, y = 24 + offset, 24 + offset
        elif isinstance(position, QPointF):
            x, y = round(position.x()), round(position.y())
        else:
            x, y = round(position[0]), round(position[1])
        if self.snap_enabled:
            x, y = round(x / GRID) * GRID, round(y / GRID) * GRID
        node = create_widget(self.document, kind, parent=parent, x=x, y=y)
        container = self.document.find(parent) if parent else None
        pw, ph = (container.width, container.height) if container else (self.document.width, self.document.height)
        node.width = min(node.width, pw)
        node.height = min(node.height, ph)
        node.x = max(0, min(node.x, pw - node.width))
        node.y = max(0, min(node.y, ph - node.height))
        self.refresh(node.id)
        self.document_changed.emit()
        return node

    def delete_selected(self):
        if self.document is None or not self.view.editable:
            return
        ids = set(self.selected_ids())
        if not ids:
            return
        while True:
            children = {node.id for node in self.document.widgets if node.parent in ids}
            if children <= ids:
                break
            ids.update(children)
        self.document.widgets[:] = [node for node in self.document.widgets if node.id not in ids]
        self.view.rebuild(self.document)
        self.document_changed.emit()

    def duplicate_selected(self):
        if self.document is None or not self.view.editable:
            return
        ids = set(self.selected_ids())
        if not ids:
            return
        roots = self._selected_roots(ids)
        originals = list(self.document.widgets)
        names = {node.name for node in originals}
        clones = []
        for root in roots:
            descendants = {root.id}
            while True:
                children = {node.id for node in originals if node.parent in descendants}
                if children <= descendants:
                    break
                descendants.update(children)
            mapping = {node_id: uuid.uuid4().hex[:12] for node_id in descendants}
            for node in originals:
                if node.id not in descendants:
                    continue
                clone = copy.deepcopy(node)
                clone.id = mapping[node.id]
                stem = node.name.rstrip("0123456789_") or "widget"
                n = 2
                while f"{stem}_{n}" in names:
                    n += 1
                clone.name = f"{stem}_{n}"
                names.add(clone.name)
                clone.parent = mapping.get(node.parent, node.parent)
                if node.id == root.id:
                    container = self.document.find(node.parent) if node.parent else None
                    pw, ph = (container.width, container.height) if container else (self.document.width, self.document.height)
                    clone.x = min(max(0, pw - clone.width), clone.x + 16)
                    clone.y = min(max(0, ph - clone.height), clone.y + 16)
                clones.append(clone)
        self.document.widgets.extend(clones)
        selected = [clone.id for clone in clones if clone.parent not in {entry.id for entry in clones}]
        self.view.rebuild(self.document, selected)
        self.document_changed.emit()

    def toggle_grid(self, enabled=None):
        enabled = not self.view.grid_enabled if enabled is None else bool(enabled)
        self.view.grid_enabled = enabled
        self.grid_button.blockSignals(True)
        self.grid_button.setChecked(enabled)
        self.grid_button.blockSignals(False)
        if self.view.artboard:
            self.view.artboard.update()

    def toggle_snap(self, enabled=None):
        enabled = not self.view.snap_enabled if enabled is None else bool(enabled)
        self.view.snap_enabled = enabled
        self.snap_button.blockSignals(True)
        self.snap_button.setChecked(enabled)
        self.snap_button.blockSignals(False)

    def _combo_zoom(self, _index=None):
        try:
            value = float(self.zoom_combo.currentText().replace("%", "").replace(",", ".")) / 100
        except ValueError:
            value = self.view.zoom
        self._set_zoom(value)

    def _set_zoom(self, zoom):
        zoom = max(.25, min(3, float(zoom)))
        self.view.resetTransform()
        self.view.scale(zoom, zoom)
        self.view.zoom = zoom
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{round(zoom * 100)}%")
        self.zoom_combo.blockSignals(False)
        self.view.viewport().update()

    def zoom_in(self):
        self._set_zoom(self.view.zoom * 1.2)

    def zoom_out(self):
        self._set_zoom(self.view.zoom / 1.2)

    def actual_size(self):
        self._set_zoom(1)

    def fit(self):
        if self.document is None:
            return
        available_w = max(100, self.view.viewport().width() - 72)
        available_h = max(100, self.view.viewport().height() - 100)
        self._set_zoom(min(available_w / self.document.width, available_h / self.document.height, 1.5))
        self.view.centerOn(self.document.width / 2, self.document.height / 2)

    def set_theme(self, theme):
        self.view.set_theme(theme)
        # Rebuild controls after QApplication propagates a new palette.  This
        # preserves selection and prevents stale partial item paints on Windows.
        if self.document is not None:
            self.refresh()

    def set_editable(self, editable):
        self.view.editable = bool(editable)
        for item in self.view.items_by_id.values():
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, bool(editable))
            item.update()
        self.hint_label.setText("Trascina · Ridimensiona · Doppio clic per il codice" if editable else "Applica le modifiche al codice per tornare al designer")
        self.snap_button.setEnabled(bool(editable))

    def _update_footer(self):
        ids = self.selected_ids()
        if len(ids) > 1:
            self.selection_label.setText(f"{len(ids)} componenti selezionati")
        elif ids and self.document:
            node = self.document.find(ids[0])
            self.selection_label.setText(f"{node.name}   ·   X {node.x}  Y {node.y}   ·   {node.width} × {node.height} px" if node else "Nessun elemento selezionato")
        else:
            self.selection_label.setText("Finestra principale · Trascina un componente per aggiungerlo")

