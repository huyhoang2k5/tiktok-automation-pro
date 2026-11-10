# Modern Dark Theme Stylesheet for TikTok Auto Like Tool

DARK_STYLE = """
QWidget {
    background-color: #12141a;
    color: #e1e7ec;
    font-family: 'Segoe UI', 'SF Pro Text', Arial, sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #232733;
    border-radius: 8px;
    margin-top: 24px;
    font-weight: bold;
    font-size: 13px;
    color: #00d2ff;
    padding-top: 15px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: #12141a;
}

QLabel {
    color: #9ba1b0;
    font-weight: 500;
}

QPlainTextEdit, QTextEdit, QLineEdit {
    background-color: #1a1d26;
    border: 1px solid #2a2f3d;
    border-radius: 6px;
    color: #ffffff;
    padding: 8px;
    selection-background-color: #0078d4;
}

QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {
    border: 1px solid #00d2ff;
}

QSpinBox {
    background-color: #1a1d26;
    border: 1px solid #2a2f3d;
    border-radius: 6px;
    color: #ffffff;
    padding: 6px 10px;
    font-weight: bold;
}

QSpinBox:focus {
    border: 1px solid #00d2ff;
}

QCheckBox {
    color: #c5cbd5;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #3c4254;
    background-color: #1a1d26;
}

QCheckBox::indicator:checked {
    background-color: #00d2ff;
    border: 1px solid #00d2ff;
}

QPushButton {
    background-color: #242938;
    color: #ffffff;
    border: 1px solid #363d52;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #2f364a;
    border-color: #4a5472;
}

QPushButton:pressed {
    background-color: #1a1e2a;
}

QPushButton:disabled {
    background-color: #161822;
    color: #555b6d;
    border-color: #212431;
}

/* Specific button styles */
QPushButton#btn_start {
    background-color: #00a86b;
    border: none;
    color: white;
}
QPushButton#btn_start:hover {
    background-color: #00c980;
}
QPushButton#btn_start:disabled {
    background-color: #1b4131;
    color: #618776;
}

QPushButton#btn_pause {
    background-color: #d97706;
    border: none;
    color: white;
}
QPushButton#btn_pause:hover {
    background-color: #f59e0b;
}

QPushButton#btn_stop {
    background-color: #dc2626;
    border: none;
    color: white;
}
QPushButton#btn_stop:hover {
    background-color: #ef4444;
}

QPushButton#btn_login {
    background-color: #2563eb;
    border: none;
    color: white;
}
QPushButton#btn_login:hover {
    background-color: #3b82f6;
}

/* QTableWidget */
QTableWidget {
    background-color: #161822;
    alternate-background-color: #1c1f2b;
    border: 1px solid #232733;
    border-radius: 8px;
    gridline-color: #202432;
    color: #e2e8f0;
    selection-background-color: #2a3147;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #1c202d;
    color: #94a3b8;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #2a3147;
    font-weight: bold;
}

QProgressBar {
    border: 1px solid #232733;
    border-radius: 6px;
    background-color: #161822;
    text-align: center;
    color: #ffffff;
    font-weight: bold;
    height: 20px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d4, stop:1 #00d2ff);
    border-radius: 5px;
}

QScrollBar:vertical {
    background-color: #12141a;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #2d3345;
    border-radius: 5px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3d465e;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* QTabWidget & QTabBar */
QTabWidget::pane {
    border: 1px solid #232733;
    border-radius: 8px;
    background-color: #12141a;
    padding: 6px;
}

QTabBar::tab {
    background-color: #161822;
    color: #94a3b8;
    border: 1px solid #232733;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 22px;
    margin-right: 4px;
    font-weight: bold;
    font-size: 13px;
}

QTabBar::tab:selected {
    background-color: #1a1e2b;
    color: #00d2ff;
    border-top: 2px solid #00d2ff;
    border-bottom: 1px solid #1a1e2b;
}

QTabBar::tab:hover:!selected {
    background-color: #212638;
    color: #e2e8f0;
}
"""
