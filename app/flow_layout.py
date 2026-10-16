"""A layout that wraps onto a new row instead of squeezing what is on the current one.

Qt ships nothing like it, and the result card needs one for a specific failure: word chips sat in
a QHBoxLayout inside a window fixed at 460px, and a long sentence segments into twenty-odd of
them. A box layout asked for more space than it can have does not refuse -- it divides the
shortfall among its children and hands each one whatever is left, ignoring their minimum widths,
which it is entitled to do because the parent cannot grow. Twenty-one chips came out 16px wide
against a natural 54px. Ten of those pixels are padding and two are the border, so the character
inside had four pixels to render in, and the click target for a definition was thinner than the
scrollbar beside it.

Wrapping is the fix rather than a minimum width because it is the only one that gives the chips
somewhere to go. Each item is laid out at its sizeHint and never below it; when the next one will
not fit, the row ends.
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    """Left-to-right, top-to-bottom, at each item's natural size."""

    def __init__(self, parent=None, spacing: int = 5):
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    # --- the five QLayout has to have -------------------------------------------------

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        # Index order is insertion order, which callers rely on: the result card matches chip i to
        # token i by position in the layout.
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    # --- sizing -----------------------------------------------------------------------

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        """Measured at the width this layout actually has, not at the width it would like.

        The distinction is the whole of it. QLayout.totalSizeHint takes the height from
        heightForWidth(sizeHint().width()), so a hint reporting the minimum width -- one chip --
        answers the question "how tall is this if every chip is on its own line", and twenty-one
        chips came back 688px tall. The host is already sitting in a window of known width by the
        time it holds anything, so ask for the height at that width instead.
        """
        width = self.geometry().width()
        if width <= 0:
            parent = self.parentWidget()
            width = parent.contentsRect().width() if parent is not None else 0
        if width <= 0:
            return self.minimumSize()
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:  # noqa: N802
        """One item wide, not one row wide.

        Asking for the width of a whole row would push the demand straight back into the fixed-
        width window this layout exists to survive. The height that goes with a given width is
        heightForWidth's business, not this one's.
        """
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    # --- the actual wrapping ------------------------------------------------------------

    def _arrange(self, rect: QRect, apply: bool) -> int:
        """Place the items in `rect`, or just measure how tall doing so would be.

        `apply=False` is the heightForWidth path and must not touch geometry: Qt calls it while
        working out what size to offer, and moving widgets from inside that is how a layout ends
        up fighting itself.
        """
        margins = self.contentsMargins()
        field = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        space = self.spacing()
        x, y, row_height = field.x(), field.y(), 0

        for item in self._items:
            hint = item.sizeHint()
            if x > field.x() and x + hint.width() - 1 > field.right():
                x = field.x()
                y += row_height + space
                row_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + space
            row_height = max(row_height, hint.height())

        return y + row_height - rect.y() + margins.bottom()


def wrap_in_flow(widget, spacing: int = 5) -> FlowLayout:
    """Give `widget` a FlowLayout and the size policy that makes Qt ask it for its height.

    The second half is not optional and is silent when missing: QVBoxLayout only consults a
    child's heightForWidth if the child's *size policy* says it has one, regardless of what the
    child's layout reports. Without this the host widget is allotted a single row's height and
    every wrapped row is drawn outside it, over whatever comes next.
    """
    layout = FlowLayout(widget, spacing=spacing)
    policy = widget.sizePolicy()
    policy.setHeightForWidth(True)
    policy.setVerticalPolicy(QSizePolicy.Minimum)
    widget.setSizePolicy(policy)
    return layout
