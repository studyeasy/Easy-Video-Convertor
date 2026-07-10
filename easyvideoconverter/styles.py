"""Qt Style Sheet (QSS) for the dark UI theme."""

COLORS = {
    "bg": "#0f1117",
    "bg_soft": "#151824",
    "card": "#1a1e2c",
    "card_hover": "#202537",
    "border": "#2a3045",
    "text": "#e8eaf2",
    "text_dim": "#9aa1b5",
    "text_faint": "#6b7288",
    "accent": "#4f8cff",
    "green": "#3ecf8e",
    "orange": "#f0a04b",
    "red": "#ef6a6a",
}

QSS = """
* { font-family: "Segoe UI"; font-size: 13px; color: #e8eaf2; }

QWidget#root { background: #0f1117; }

/* ---- top bar ---- */
QWidget#topbar { background: #151824; border-bottom: 1px solid #2a3045; }
QLabel#title { font-size: 17px; font-weight: 600; color: #e8eaf2; }
QLabel#tagline { font-size: 12px; color: #6b7288; }
QLabel#credit { font-size: 11px; color: #55607a; margin-top: 2px; }
QLabel#credit a { color: #4f8cff; text-decoration: none; }

QLabel#hwBadge {
    font-size: 12px; padding: 6px 14px; border-radius: 12px;
    background: rgba(79,140,255,0.14); color: #4f8cff;
    border: 1px solid rgba(79,140,255,0.30);
}
QLabel#hwBadge[kind="gpu"] {
    background: rgba(62,207,142,0.12); color: #3ecf8e; border: 1px solid rgba(62,207,142,0.30);
}
QLabel#hwBadge[kind="cpu"] {
    background: rgba(240,160,75,0.12); color: #f0a04b; border: 1px solid rgba(240,160,75,0.30);
}

/* ---- ffmpeg banner ---- */
QWidget#banner { background: rgba(240,160,75,0.12); border-bottom: 1px solid rgba(240,160,75,0.30); }
QLabel#bannerText { color: #f0a04b; font-size: 13px; }

/* ---- drop zone ---- */
QFrame#dropZone {
    border: 2px dashed #2a3045; border-radius: 12px; background: transparent;
}
QFrame#dropZone[drag="true"] { border: 2px dashed #4f8cff; background: rgba(79,140,255,0.08); }
QLabel#dzTitle { font-size: 16px; font-weight: 600; color: #e8eaf2; }
QFrame#dropZone[compact="true"] QLabel#dzTitle { font-size: 12.5px; font-weight: 500; color: #9aa1b5; }
QLabel#dzSub { font-size: 12px; color: #6b7288; }

/* ---- sidebar ---- */
QWidget#sidebarWrap { background: #151824; border-left: 1px solid #2a3045; }
QScrollArea#sidebarScroll { background: transparent; border: none; }
QWidget#sidebar { background: #151824; }
QWidget#sidebarFooter { background: #12151f; border-top: 1px solid #2a3045; }
QLabel[role="settingsHead"] { font-size: 12px; font-weight: 700; color: #6b7288; letter-spacing: 1px; }
QLabel[role="settingLabel"] { font-size: 13px; font-weight: 600; color: #e8eaf2; }
QLabel[role="hint"] { font-size: 11px; color: #6b7288; }

/* ---- segmented buttons ---- */
QPushButton[seg="true"] {
    background: #0f1117; color: #9aa1b5; border: 1px solid #2a3045;
    padding: 7px 4px; border-radius: 7px; font-size: 12px; font-weight: 600;
}
QPushButton[seg="true"]:hover { color: #e8eaf2; }
QPushButton[seg="true"]:checked { background: #4f8cff; color: #ffffff; border: 1px solid #4f8cff; }
QPushButton[seg="true"]:disabled { color: #3a4055; }

/* ---- normal buttons ---- */
QPushButton {
    background: #1a1e2c; color: #e8eaf2; border: 1px solid #2a3045;
    padding: 9px 16px; border-radius: 9px; font-size: 13px; font-weight: 600;
}
QPushButton:hover { background: #202537; border: 1px solid #3a4160; }
QPushButton:disabled { color: #55607a; }

QPushButton#ghost { background: transparent; }
QPushButton#small { padding: 5px 12px; font-size: 12px; background: transparent; }

QPushButton#primary {
    background: #4f8cff; color: #ffffff; border: 1px solid #4f8cff;
    padding: 12px; font-size: 15px; font-weight: 700; border-radius: 9px;
}
QPushButton#primary:hover { background: #659aff; }
QPushButton#primary:disabled { background: #263050; color: #6b7288; border: 1px solid #263050; }

QPushButton#danger {
    background: transparent; color: #ef6a6a; border: 1px solid #ef6a6a;
    padding: 12px; font-size: 14px; font-weight: 700; border-radius: 9px;
}
QPushButton#danger:hover { background: rgba(239,106,106,0.12); }

QPushButton#link {
    background: transparent; border: none; color: #4f8cff; font-size: 12px;
    text-decoration: underline; padding: 0;
}

/* ---- checkbox ---- */
QCheckBox { font-size: 13px; font-weight: 600; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #2a3045; background: #0f1117; }
QCheckBox::indicator:checked { background: #4f8cff; border: 1px solid #4f8cff; image: url("@CHECK@"); }
QCheckBox:disabled { color: #55607a; }

/* ---- output field ---- */
QLineEdit#outDir {
    background: #0f1117; border: 1px solid #2a3045; border-radius: 8px;
    padding: 7px 10px; color: #9aa1b5; font-size: 12px;
}

/* ---- file cards ---- */
QScrollArea { border: none; background: transparent; }
QWidget#listContainer { background: transparent; }

QFrame#fileCard { background: #1a1e2c; border: 1px solid #2a3045; border-radius: 12px; }
QLabel#fcName { font-size: 13px; font-weight: 600; color: #e8eaf2; }
QLabel#fcMeta { font-size: 12px; color: #6b7288; }
QLabel#fcStatus { font-size: 12px; color: #9aa1b5; }
QLabel#fcStatus[state="done"] { color: #3ecf8e; font-weight: 600; }
QLabel#fcStatus[state="error"] { color: #ef6a6a; }
QLabel#fcStatus[state="converting"] { color: #4f8cff; }
QLabel#fcStatus[state="grew"] { color: #f0a04b; }
QLabel#fcError { font-size: 11px; color: #ef6a6a; }
QPushButton#fcRemove { background: transparent; border: none; color: #6b7288; font-size: 15px; padding: 2px 6px; }
QPushButton#fcRemove:hover { color: #ef6a6a; }

/* ---- progress bars ---- */
QProgressBar { background: #0f1117; border: none; border-radius: 3px; height: 6px; text-align: center; }
QProgressBar::chunk { background: #4f8cff; border-radius: 3px; }

QLabel#listCount { color: #9aa1b5; font-size: 13px; }
QLabel#overallText { color: #9aa1b5; font-size: 12px; }

QFrame#summary { background: rgba(62,207,142,0.10); border: 1px solid rgba(62,207,142,0.30); border-radius: 10px; }
QLabel#summaryBig { color: #3ecf8e; font-size: 16px; font-weight: 700; }
QLabel#summaryText { color: #3ecf8e; font-size: 12px; }

QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #2a3045; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""
