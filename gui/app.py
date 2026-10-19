"""Pivot Benchmark GUI (PySide6).

A front end over `RunManager`. The engine runs on its own thread inside the
manager; events are marshalled onto the Qt thread through one signal. Every
view reads the sqlite file through the manager, so the same window can inspect
a finished run, a run in progress, or a run copied from another machine.

Charts are QPainter only: no QtCharts, no matplotlib.
"""

from __future__ import annotations

import difflib
import html
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QRadioButton, QSizePolicy,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from mbench import analyze
from mbench.ladder import Ladder
from mbench.manager import RunManager
from mbench.metrics import HEADLINE, MODES

SEG_COLORS = {"live": "#2a78d6", "script": "#6b6b6b", "fallback": "#b3771e",
              "slot": "#111111", "ask": "#1baf7a", "manual": "#d95926", "fact": "#4a3aa7"}
MODE_COLORS = {"capitulate": "#2a78d6", "hostile": "#e34948", "refuse": "#eda100",
               "collapse": "#4a3aa7"}
FAMILY_COLORS = {"insult": "#e34948", "denial": "#2a78d6", "paranoid": "#4a3aa7", "deception": "#b3771e", "-": "#888888"}
DARK_SEG = {"slot": "#f0f0f0", "script": "#b0b0b0"}


class Bridge(QObject):
    event = Signal(str, dict)


def _dark(app: QApplication) -> bool:
    return app.palette().window().color().lightness() < 128


def _seg_html(segments: list[dict], dark: bool) -> str:
    parts = []
    for seg in segments:
        src = seg.get("source", "slot")
        if src == "fact":
            continue
        col = (DARK_SEG.get(src) if dark else None) or SEG_COLORS.get(src, "#333")
        text = html.escape(seg.get("text", ""))
        if seg.get("changed"):
            w = html.escape(seg["changed"])
            style = "color:#e34948;background:#ffe9e9" if seg.get("new") else "color:#e34948"
            text = text.replace(w, f'<b style="{style}">{w}</b>', 1)
        if seg.get("insulted") and not seg.get("new"):
            text = f'<span style="text-decoration:underline">{text}</span>'
        parts.append(f'<span style="color:{col}">{text}</span>')
    return "<p>" + " ".join(parts) + "</p>"


def _fmt(v, nd=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _attack_label(atk: dict | None) -> str:
    if not atk:
        return ""
    if atk.get("kind") == "random":
        return f"  random dose {atk.get('n_insults')}"
    return f"  {atk.get('slot')}: {atk.get('before')}->{atk.get('after')}"


# ---------------------------------------------------------------------------
# chart
# ---------------------------------------------------------------------------

class CurveChart(QWidget):
    """x = attack-phase message index. The descent occupies 1..N (dose = x),
    the random phase follows. A grey area shows the dose of every message."""

    PAD_L, PAD_R, PAD_T, PAD_B = 48, 14, 24, 40

    def __init__(self, dark: bool):
        super().__init__()
        self.dark = dark
        self.rows: list[dict] = []
        self.control_rows: list[dict] = []
        self.endpoints: dict = {}
        self.fit: dict = {}
        self.canary: dict = {}
        self.offset = 0
        self.n_slots = 15
        self.n_desc = 0
        self.show = {"frac_broken": True, "modes": True, "valence": True,
                     "self_abasement_rate": True, "mirroring": False, "canary": True,
                     "fit": True, "control": True, "dose": True}
        self.setMinimumHeight(360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    @staticmethod
    def _index(rows):
        out = [r for r in rows if r["phase"] in ("descent", "random")]
        for i, r in enumerate(out, start=1):
            r["_x"] = i
        return out

    def set_data(self, rows, endpoints, fit, canary, offset, n_slots, control_rows=None):
        self.rows = self._index(rows)
        self.control_rows = self._index(control_rows or [])
        self.n_desc = sum(1 for r in self.rows if r["phase"] == "descent")
        self.endpoints, self.fit, self.canary, self.offset = endpoints, fit, canary, offset
        self.n_slots = max(1, n_slots or 15)
        self.update()

    def _c(self, light, dark):
        return QColor(dark if self.dark else light)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, self._c("#fcfcfb", "#1a1a19"))
        plot = QRectF(self.PAD_L, self.PAD_T, w - self.PAD_L - self.PAD_R,
                      h - self.PAD_T - self.PAD_B)
        f = QFont(); f.setPointSize(8); p.setFont(f)
        if len(self.rows) < 2:
            p.setPen(QPen(self._c("#52514e", "#c3c2b7")))
            p.drawText(plot, Qt.AlignCenter, "no attack-phase data yet")
            return
        lo, hi = 1, max(r["_x"] for r in self.rows)
        hi = max(hi, lo + 1)

        def X(x):
            return plot.left() + plot.width() * (x - lo) / (hi - lo)

        def Y(v):
            return plot.bottom() - plot.height() * max(0.0, min(1.0, v))

        # dose area
        legend = []
        if self.show["dose"]:
            poly = QPolygonF([QPointF(X(lo), Y(0))])
            for r in self.rows:
                poly.append(QPointF(X(r["_x"]), Y(r["dose"] / self.n_slots)))
            poly.append(QPointF(X(hi), Y(0)))
            col = self._c("#d9d8d0", "#33332f")
            p.setBrush(QBrush(col)); p.setPen(Qt.NoPen); p.drawPolygon(poly)
            legend.append(("dose / traits", col.name()))
        p.setPen(QPen(self._c("#e1e0d9", "#2c2c2a"), 1))
        for i in range(5):
            y = plot.bottom() - plot.height() * i / 4
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QPen(self._c("#52514e", "#c3c2b7")))
            p.drawText(QRectF(0, y - 8, self.PAD_L - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{i / 4:.2f}")
            p.setPen(QPen(self._c("#e1e0d9", "#2c2c2a"), 1))
        p.setPen(QPen(self._c("#52514e", "#c3c2b7")))
        for x in sorted(set([lo, hi] + [r["_x"] for r in self.rows if r["_x"] % 5 == 0])):
            p.drawText(QRectF(X(x) - 20, plot.bottom() + 4, 40, 14), Qt.AlignHCenter, f"#{x}")
        if 0 < self.n_desc < hi:
            xb = X(self.n_desc + 0.5)
            pen = QPen(self._c("#52514e", "#c3c2b7"), 1); pen.setDashPattern([4, 3])
            p.setPen(pen); p.drawLine(QPointF(xb, plot.top()), QPointF(xb, plot.bottom()))
            p.drawText(QRectF(xb + 3, plot.bottom() - 14, 120, 12), Qt.AlignLeft, "random phase")

        def line(key_fn, color, width=2, dash=None, rows=None):
            rows = rows if rows is not None else self.rows
            pts = [QPointF(X(r["_x"]), Y(key_fn(r))) for r in rows]
            if len(pts) < 2:
                return
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            pen = QPen(QColor(color), width)
            if dash:
                pen.setDashPattern(dash)
            p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPath(path)

        if self.show["modes"]:
            for m in MODES:
                line(lambda r, mo=m: r["modes"].get(mo, 0.0), MODE_COLORS[m], 1)
                legend.append((m, MODE_COLORS[m]))
        if self.show["valence"]:
            line(lambda r: (r["means"].get("valence", 0.0) + 1) / 2, "#008300", 1, [3, 3])
            legend.append(("valence (0.5=neutral)", "#008300"))
        if self.show["self_abasement_rate"]:
            line(lambda r: min(1.0, r["means"].get("self_abasement_rate", 0.0) / 10.0),
                 "#e87ba4", 1, [1, 2])
            legend.append(("abasement/10", "#e87ba4"))
        if self.show["mirroring"]:
            line(lambda r: r["means"].get("mirroring", 0.0), "#00a0a0", 1, [4, 2])
            legend.append(("mirroring", "#00a0a0"))
        if self.show["control"] and self.control_rows:
            line(lambda r: r["frac_broken"], "#888888", 2, [6, 3], rows=self.control_rows)
            legend.append(("control broken", "#888888"))
        if self.show["frac_broken"]:
            line(lambda r: r["frac_broken"], "#111111" if not self.dark else "#ffffff", 3)
            legend.append(("broken", "#111111" if not self.dark else "#ffffff"))
        if self.show["fit"] and self.fit.get("s50") is not None and self.fit.get("slope") and self.n_desc:
            s50, k = self.fit["s50"], self.fit["slope"]
            pts = []
            for i in range(60):
                x = 1 + (self.n_desc - 1) * i / 59
                pts.append(QPointF(X(x), Y(1 / (1 + math.exp(-k * (x - s50))))))
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            pen = QPen(QColor("#eb6834"), 2); pen.setDashPattern([2, 2])
            p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPath(path)
            legend.append((f"descent logistic s50={s50}", "#eb6834"))
        if self.show["canary"] and self.canary:
            p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor("#eda100")))
            for t, d in self.canary.items():
                x = t - self.offset
                if lo <= x <= hi and "context" in d:
                    p.drawEllipse(QPointF(X(x), Y(d["context"])), 4, 4)
            legend.append(("canary (context)", "#eda100"))
        f2 = QFont(); f2.setPointSize(7); p.setFont(f2)
        row = 0
        for key in ("s_tone", "s_break", "s_capitulate", "s_hostile", "s_refuse", "s_collapse"):
            s = self.endpoints.get(key)
            if s is None or not (lo <= s <= self.n_desc):
                continue
            pen = QPen(self._c("#0b0b0b", "#ffffff"), 1); pen.setDashPattern([2, 3])
            p.setPen(pen)
            p.drawLine(QPointF(X(s), plot.top()), QPointF(X(s), plot.bottom()))
            p.drawText(QRectF(X(s) + 2, plot.top() + row * 11, 90, 12), Qt.AlignLeft,
                       key.replace("s_", ""))
            row += 1
        p.setFont(f)
        x, y = self.PAD_L, h - 16
        for label, col in legend:
            p.setBrush(QBrush(QColor(col))); p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y + 2, 9, 9), 2, 2)
            p.setPen(QPen(self._c("#52514e", "#c3c2b7")))
            wdt = 7 * len(label) + 12
            p.drawText(QRectF(x + 12, y - 2, wdt, 16), Qt.AlignLeft, label)
            x += 12 + wdt
            if x > w - 80:
                break


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------

class Main(QMainWindow):
    def __init__(self, mgr: RunManager, app: QApplication):
        super().__init__()
        self.mgr = mgr
        self.dark = _dark(app)
        self.setWindowTitle("Pivot Benchmark")
        self.resize(1320, 880)
        self.bridge = Bridge()
        self.bridge.event.connect(self.on_engine_event)
        mgr.listeners.append(lambda kind, payload: self.bridge.event.emit(kind, payload))
        self.current_run: str | None = None
        self.control_run: str | None = None
        self._band: list[dict] = []
        self._band_i = 0
        self._turns: list[dict] = []
        self._attack_rows: list[dict] = []

        top = QWidget(); tl = QHBoxLayout(top); tl.setContentsMargins(8, 6, 8, 0)
        tl.addWidget(QLabel("run:"))
        self.picker = QComboBox(); self.picker.setMinimumWidth(420)
        self.picker.currentIndexChanged.connect(self._pick_run)
        tl.addWidget(self.picker, 1)
        self.refresh_btn = QPushButton("refresh"); self.refresh_btn.clicked.connect(self.refresh_runs)
        tl.addWidget(self.refresh_btn)
        self.status_lab = QLabel(""); tl.addWidget(self.status_lab)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_run(), "Run")
        self.tabs.addTab(self._tab_transcript(), "Transcript")
        self.tabs.addTab(self._tab_attacks(), "Attacks")
        self.tabs.addTab(self._tab_script(), "Script editor")
        self.tabs.addTab(self._tab_intervene(), "Intervene")
        self.tabs.addTab(self._tab_curves(), "Curves")
        self.tabs.addTab(self._tab_compare(), "Compare")
        self.tabs.addTab(self._tab_label(), "Label")
        self.tabs.addTab(self._tab_report(), "Report")
        self.tabs.addTab(self._tab_settings(), "Settings")
        self.tabs.currentChanged.connect(lambda _i: self._refresh_current_tab())

        root = QWidget(); lay = QVBoxLayout(root); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(top); lay.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self.refresh_runs()
        self.timer = QTimer(self); self.timer.timeout.connect(self._tick); self.timer.start(1500)

    # -- tabs -------------------------------------------------------------------
    def _tab_run(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        form = QFormLayout()
        self.f_name = QLineEdit(self.mgr.cfg.get("run_name", "run"))
        self.f_subject = QComboBox(); self.f_adversary = QComboBox()
        for m in self.mgr.models("A"):
            self.f_subject.addItem(f"{m['name']}  ({'key ok' if m['has_key'] else 'needs ' + str(m['key_env'])})", m["name"])
        for m in self.mgr.models("B"):
            self.f_adversary.addItem(f"{m['name']}  ({'key ok' if m['has_key'] else 'needs ' + str(m['key_env'])})", m["name"])
        self._select(self.f_subject, self.mgr.cfg["subject"]["model"])
        self._select(self.f_adversary, self.mgr.cfg["adversary"]["model"])
        self.f_profile = QComboBox(); self.f_profile.addItems(list(self.mgr.cfg["profiles"]))
        self.f_profile.setCurrentText(self.mgr.cfg.get("profile", "local"))
        self.f_ladder = QComboBox()
        for name in sorted(os.listdir(os.path.join(self.mgr.root, "ladders"))):
            if name.endswith(".yaml"):
                self.f_ladder.addItem(f"ladders/{name}", f"ladders/{name}")
        self._select(self.f_ladder, self.mgr.cfg["ladder"])
        pr = self.mgr.cfg["probe"]
        self.f_k = QSpinBox(); self.f_k.setRange(1, 64); self.f_k.setValue(int(pr.get("k", 4)))
        self.f_workers = QSpinBox(); self.f_workers.setRange(1, 16); self.f_workers.setValue(int(pr.get("workers", 1)))
        self.f_window = QSpinBox(); self.f_window.setRange(1, 400); self.f_window.setValue(int(pr.get("history_window", 12)))
        self.f_every = QSpinBox(); self.f_every.setRange(0, 100); self.f_every.setValue(int(self.mgr.cfg["canary"].get("every", 5)))
        self.f_random = QSpinBox(); self.f_random.setRange(0, 1000)
        self.f_random.setValue(int(self.mgr.cfg["profiles"][self.mgr.cfg.get("profile", "local")].get("n_random", 30)))
        self.f_max = QSpinBox(); self.f_max.setRange(0, 1000); self.f_max.setValue(int(pr.get("max_attacks") or 0))
        self.f_max.setSpecialValueText("all")
        self.f_live = QCheckBox("live bridge sentences from B"); self.f_live.setChecked(bool(self.mgr.cfg["adversary"].get("live_bridge", True)))
        form.addRow("run name", self.f_name); form.addRow("subject A", self.f_subject)
        form.addRow("adversary B", self.f_adversary); form.addRow("profile", self.f_profile)
        form.addRow("ladder", self.f_ladder); form.addRow("k samples / turn", self.f_k)
        form.addRow("workers", self.f_workers); form.addRow("history window (turns)", self.f_window)
        form.addRow("canary every N turns", self.f_every)
        form.addRow("random-phase messages", self.f_random)
        form.addRow("cap on attack messages", self.f_max)
        form.addRow("", self.f_live)
        lay.addLayout(form)
        btns = QHBoxLayout()
        self.b_start = QPushButton("Start"); self.b_pause = QPushButton("Pause")
        self.b_resume = QPushButton("Resume"); self.b_stop = QPushButton("Stop")
        self.b_cont = QPushButton("Continue stopped run")
        for b in (self.b_start, self.b_pause, self.b_resume, self.b_stop, self.b_cont):
            btns.addWidget(b)
        self.b_start.clicked.connect(self.start_run); self.b_pause.clicked.connect(lambda: self.mgr.pause(self.current_run))
        self.b_resume.clicked.connect(lambda: self.mgr.unpause(self.current_run))
        self.b_stop.clicked.connect(lambda: self.mgr.stop(self.current_run))
        self.b_cont.clicked.connect(self.continue_run)
        lay.addLayout(btns)
        self.progress = QProgressBar(); lay.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000)
        lay.addWidget(self.log, 1)
        return w

    def _tab_transcript(self) -> QWidget:
        split = QSplitter()
        self.t_list = QListWidget(); self.t_list.currentRowChanged.connect(self._show_turn)
        split.addWidget(self.t_list)
        right = QWidget(); rl = QVBoxLayout(right)
        self.t_b = QTextBrowser(); self.t_b.setOpenExternalLinks(False)
        rl.addWidget(QLabel("B  (blue = live bridge, grey = script, orange = fallback/manual, "
                            "green = request, red = insult word, highlighted = newly flipped, "
                            "underlined = already insulted)"))
        rl.addWidget(self.t_b, 2)
        rl.addWidget(QLabel("A samples"))
        self.t_a = QTextBrowser(); rl.addWidget(self.t_a, 3)
        split.addWidget(right); split.setSizes([300, 1000])
        return split

    def _tab_attacks(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        filt = QHBoxLayout()
        self.a_kind = QComboBox(); self.a_kind.addItems(["all", "descent", "random"])
        self.a_family = QComboBox(); self.a_family.addItems(["all", "insult", "denial", "paranoid"])
        self.a_slot = QComboBox(); self.a_slot.addItem("all traits")
        self.a_minint = QSpinBox(); self.a_minint.setRange(0, 10)
        self.a_ctrl = QComboBox(); self.a_ctrl.addItem("(no control run)", None)
        for x in (self.a_kind, self.a_family, self.a_slot):
            x.currentIndexChanged.connect(self._fill_attacks)
        self.a_minint.valueChanged.connect(self._fill_attacks)
        self.a_ctrl.currentIndexChanged.connect(self._pick_control)
        filt.addWidget(QLabel("phase")); filt.addWidget(self.a_kind)
        filt.addWidget(QLabel("family")); filt.addWidget(self.a_family)
        filt.addWidget(QLabel("trait")); filt.addWidget(self.a_slot)
        filt.addWidget(QLabel("min intensity")); filt.addWidget(self.a_minint)
        filt.addWidget(QLabel("control run")); filt.addWidget(self.a_ctrl, 1)
        lay.addLayout(filt)
        split = QSplitter(Qt.Vertical)
        self.a_table = QTableWidget(0, 11)
        self.a_table.setHorizontalHeaderLabels(["phase", "#", "turn", "dose", "trait", "family",
                                                "int", "cum", "praise word -> insult word",
                                                "played", "broken"])
        self.a_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.a_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.a_table.itemSelectionChanged.connect(self._show_attack)
        split.addWidget(self.a_table)
        self.a_detail = QTextBrowser(); split.addWidget(self.a_detail)
        split.setSizes([350, 450])
        lay.addWidget(split, 1)
        btns = QHBoxLayout()
        b1 = QPushButton("Jump to transcript"); b1.clicked.connect(self._jump_from_attack)
        b2 = QPushButton("Re-roll this message (new seeds)"); b2.clicked.connect(self._reroll_attack)
        btns.addWidget(b1); btns.addWidget(b2); btns.addStretch(1)
        lay.addLayout(btns)
        return w

    def _tab_script(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel("The ladder as it will be played from the next turn: traits, descent "
                             "order, random schedule. Played traits and messages are locked; saving "
                             "while paused records a revision with a new hash."))
        split = QSplitter()
        self.s_edit = QPlainTextEdit(); self.s_edit.setFont(QFont("Consolas", 9))
        split.addWidget(self.s_edit)
        self.s_diff = QPlainTextEdit(); self.s_diff.setReadOnly(True); self.s_diff.setFont(QFont("Consolas", 9))
        split.addWidget(self.s_diff); split.setSizes([700, 500])
        lay.addWidget(split, 1)
        btns = QHBoxLayout()
        b1 = QPushButton("Validate"); b1.clicked.connect(self._validate_script)
        b2 = QPushButton("Show diff"); b2.clicked.connect(self._diff_script)
        b3 = QPushButton("Save as revision (run must be paused)"); b3.clicked.connect(self._save_script)
        b4 = QPushButton("Reload"); b4.clicked.connect(self._load_script)
        for b in (b1, b2, b3, b4):
            btns.addWidget(b)
        btns.addStretch(1); lay.addLayout(btns)
        self.s_msg = QLabel(""); lay.addWidget(self.s_msg)
        return w

    def _tab_intervene(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        g1 = QGroupBox("Manual B turn (used as the next B message; logged as an intervention)")
        l1 = QVBoxLayout(g1)
        self.i_text = QPlainTextEdit(); l1.addWidget(self.i_text)
        b = QPushButton("Queue as next B turn"); b.clicked.connect(self._manual_b); l1.addWidget(b)
        lay.addWidget(g1, 2)
        g2 = QGroupBox("Re-roll a turn's A samples with shifted seeds")
        l2 = QHBoxLayout(g2)
        self.i_turn = QSpinBox(); self.i_turn.setRange(1, 100000)
        self.i_shift = QSpinBox(); self.i_shift.setRange(1, 1000); self.i_shift.setValue(1)
        b2 = QPushButton("Re-roll"); b2.clicked.connect(self._reroll)
        l2.addWidget(QLabel("turn")); l2.addWidget(self.i_turn); l2.addWidget(QLabel("seed shift"))
        l2.addWidget(self.i_shift); l2.addWidget(b2); l2.addStretch(1)
        lay.addWidget(g2)
        lay.addWidget(QLabel("Intervention and event log"))
        self.i_log = QPlainTextEdit(); self.i_log.setReadOnly(True); lay.addWidget(self.i_log, 2)
        return w

    def _tab_curves(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        self.chart = CurveChart(self.dark)
        lay.addWidget(self.chart, 1)
        row = QHBoxLayout()
        self.c_checks = {}
        for key, label in (("dose", "dose"), ("frac_broken", "broken"), ("modes", "modes"),
                           ("valence", "valence"), ("self_abasement_rate", "abasement"),
                           ("mirroring", "mirroring"), ("canary", "canary"),
                           ("fit", "logistic fit"), ("control", "control")):
            cb = QCheckBox(label); cb.setChecked(self.chart.show[key])
            cb.stateChanged.connect(lambda _s, k=key, c=cb: self._toggle_series(k, c.isChecked()))
            self.c_checks[key] = cb; row.addWidget(cb)
        row.addStretch(1); lay.addLayout(row)
        self.c_summary = QLabel(""); self.c_summary.setWordWrap(True); lay.addWidget(self.c_summary)
        return w

    def _tab_compare(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        self.cmp_table = QTableWidget(0, 16)
        self.cmp_table.setHorizontalHeaderLabels(["run", "name", "subject", "persona", "adversary", "ladder", "ladder set",
                                                  "status", "s50", "density", "s_break", "mode",
                                                  "r50", "scarring", "confound", "publishable"])
        self.cmp_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.cmp_table.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self.cmp_table, 1)
        btns = QHBoxLayout()
        b = QPushButton("Refresh"); b.clicked.connect(self._fill_compare); btns.addWidget(b)
        b2 = QPushButton("Difference of two selected (hostile - control)"); b2.clicked.connect(self._diff_runs)
        btns.addWidget(b2); btns.addStretch(1); lay.addLayout(btns)
        self.cmp_msg = QLabel(""); self.cmp_msg.setWordWrap(True); lay.addWidget(self.cmp_msg)
        lay.addWidget(QLabel("Profile triangle per subject (D10): one hostile run per persona; "
                             "censored s50 shown as censored, never as a number"))
        self.prof_table = QTableWidget(0, 7)
        self.prof_table.setHorizontalHeaderLabels(["subject", "persona", "s50", "density", "mode",
                                                   "scarring", "ctrl diff"])
        self.prof_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        lay.addWidget(self.prof_table, 1)
        return w

    def _tab_label(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Samples drawn from the transition band. Your label is compared with "
                             "the lexical classifier; kappa >= 0.6 unlocks the validity gate."))
        self.l_info = QLabel(""); lay.addWidget(self.l_info)
        self.l_b = QTextBrowser(); self.l_a = QTextBrowser()
        split = QSplitter(); split.addWidget(self.l_b); split.addWidget(self.l_a)
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        self.l_group = QButtonGroup(self)
        for lab in ("none", "holding") + MODES:
            rb = QRadioButton(lab); self.l_group.addButton(rb); row.addWidget(rb)
        b1 = QPushButton("Save label & next"); b1.clicked.connect(self._save_label)
        b2 = QPushButton("Skip"); b2.clicked.connect(self._next_label)
        b3 = QPushButton("Draw band sample"); b3.clicked.connect(self._draw_band)
        row.addWidget(b1); row.addWidget(b2); row.addWidget(b3); row.addStretch(1)
        lay.addLayout(row)
        self.l_kappa = QLabel(""); lay.addWidget(self.l_kappa)
        return w

    def _tab_report(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.r_ci = QCheckBox("bootstrap CI (slow)"); row.addWidget(self.r_ci)
        self.r_examples = QCheckBox("Show trait examples"); self.r_examples.setChecked(True)
        self.r_examples.stateChanged.connect(lambda _s: self._fill_report()); row.addWidget(self.r_examples)
        bf = QPushButton("Full report (with A's reply at every flip)"); bf.clicked.connect(self._fill_full_report)
        row.addWidget(bf)
        b = QPushButton("Refresh"); b.clicked.connect(self._fill_report); row.addWidget(b)
        b2 = QPushButton("Recompute metrics (lexicon/thresholds)"); b2.clicked.connect(self._recompute)
        row.addWidget(b2); row.addStretch(1); lay.addLayout(row)
        self.r_text = QPlainTextEdit(); self.r_text.setReadOnly(True); self.r_text.setFont(QFont("Consolas", 9))
        lay.addWidget(self.r_text, 1)
        return w

    def _tab_settings(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Credentials are stored only in ~/.pivot-benchmark/credentials.json "
                             "(or read from the environment). Leave a field blank to keep the current value; "
                             "type - to delete it."))
        self.k_form = QFormLayout(); self.k_edits = {}
        for c in self.mgr.credential_status():
            e = QLineEdit(); e.setEchoMode(QLineEdit.Password)
            e.setPlaceholderText(c["masked"] or "not set")
            self.k_edits[c["env"]] = e
            self.k_form.addRow(f"{c['provider']}  ({c['env']})", e)
        lay.addLayout(self.k_form)
        b = QPushButton("Save credentials"); b.clicked.connect(self._save_keys); lay.addWidget(b)
        g = QGroupBox("LLM judge (second labeller for kappa)"); gl = QHBoxLayout(g)
        self.j_kind = QComboBox(); self.j_kind.addItems(["none", "anthropic", "local"])
        self.j_kind.setCurrentText((self.mgr.cfg.get("judge") or {}).get("kind", "none"))
        self.j_model = QComboBox()
        for m in self.mgr.models("judge"):
            self.j_model.addItem(m["name"], m["name"])
        self.j_n = QSpinBox(); self.j_n.setRange(5, 500); self.j_n.setValue(int((self.mgr.cfg.get("judge") or {}).get("n", 60)))
        bj = QPushButton("Run judge on current run"); bj.clicked.connect(self._run_judge)
        gl.addWidget(QLabel("kind")); gl.addWidget(self.j_kind); gl.addWidget(QLabel("model"))
        gl.addWidget(self.j_model, 1); gl.addWidget(QLabel("n")); gl.addWidget(self.j_n); gl.addWidget(bj)
        lay.addWidget(g)
        self.j_msg = QLabel(""); self.j_msg.setWordWrap(True); lay.addWidget(self.j_msg)
        lay.addStretch(1)
        return w

    # -- helpers ------------------------------------------------------------------
    @staticmethod
    def _select(combo: QComboBox, data):
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return

    def refresh_runs(self):
        cur = self.current_run
        self.picker.blockSignals(True); self.picker.clear()
        self.a_ctrl.blockSignals(True); self.a_ctrl.clear(); self.a_ctrl.addItem("(no control run)", None)
        for r in self.mgr.runs():
            lab = (f"{r['run_id']}  {r['status']:8s} {r['run_name'] or ''}  A={r['subject']} "
                   f"{r.get('persona') or ''} {r['ladder_id']} [{r.get('ladder_set') or 'no set'}] turn={r['last_turn']}")
            self.picker.addItem(lab, r["run_id"])
            if r.get("ladder_kind") == "control":
                self.a_ctrl.addItem(lab, r["run_id"])
        self.picker.blockSignals(False); self.a_ctrl.blockSignals(False)
        if cur:
            self._select(self.picker, cur)
        elif self.picker.count():
            self.picker.setCurrentIndex(0)
        self._pick_run()

    def _pick_run(self, _i=0):
        self.current_run = self.picker.currentData()
        self._refresh_current_tab()
        self._tick()

    def _pick_control(self, _i=0):
        self.control_run = self.a_ctrl.currentData()
        self._fill_curves()

    def _refresh_current_tab(self):
        if not self.current_run:
            return
        i = self.tabs.currentIndex()
        {1: self._fill_transcript, 2: self._fill_attacks, 3: self._load_script,
         4: self._fill_events, 5: self._fill_curves, 6: self._fill_compare,
         7: self._draw_band_if_empty, 8: self._fill_report}.get(i, lambda: None)()

    def _tick(self):
        if not self.current_run:
            return
        st = self.mgr.status(self.current_run)
        total = st.get("total_turns") or 0
        last = st.get("last_turn") or 0
        if total:
            self.progress.setMaximum(total); self.progress.setValue(last)
        s = f"{st['db_status']}"
        if st["alive"]:
            s += "  (engine thread alive" + (", paused)" if st["paused"] else ")")
        self.status_lab.setText(s)

    def on_engine_event(self, kind: str, payload: dict):
        run = payload.get("_run")
        if kind == "turn":
            t = payload
            self.log.appendPlainText(
                f"[{run}] turn {t['turn_idx']} {t['phase']} dose={t['step']} "
                f"{t.get('request_id') or ''} broken={t['frac_broken']:.2f} "
                f"bridge={t.get('bridge_source')}" + _attack_label(t.get("attack")))
            if run == self.current_run and self.tabs.currentIndex() in (1, 2, 5):
                self._refresh_current_tab()
        elif kind == "status":
            self.log.appendPlainText(f"[{run}] status {payload.get('status')} {payload.get('error', '')}")
            if payload.get("status") == "running" and run and run != self.current_run:
                self.refresh_runs(); self._select(self.picker, run)
        elif kind == "error":
            self.log.appendPlainText(f"[{run}] ERROR {payload.get('error')}")
        else:
            self.log.appendPlainText(f"[{run}] {kind} {payload}")
        self._tick()

    # -- run tab -----------------------------------------------------------------------
    def start_run(self):
        ov = {"subject": {"model": self.f_subject.currentData()},
              "adversary": {"model": self.f_adversary.currentData(),
                            "live_bridge": self.f_live.isChecked()},
              "profile": self.f_profile.currentText(), "ladder": self.f_ladder.currentData(),
              "probe": {"k": self.f_k.value(), "workers": self.f_workers.value(),
                        "history_window": self.f_window.value(),
                        "max_attacks": self.f_max.value() or None,
                        "n_random": self.f_random.value()},
              "canary": {"every": self.f_every.value()}}
        # the profile's n_random is what the orchestrator reads first
        prof = dict(self.mgr.cfg["profiles"][self.f_profile.currentText()])
        prof["n_random"] = self.f_random.value()
        ov["profiles"] = {self.f_profile.currentText(): prof}
        try:
            rid = self.mgr.start(ov, run_name=self.f_name.text().strip() or None)
        except Exception as e:
            QMessageBox.critical(self, "start failed", str(e)); return
        self.log.appendPlainText(f"started {rid}")
        QTimer.singleShot(300, lambda: (self.refresh_runs(), self._select(self.picker, rid)))

    def continue_run(self):
        if not self.current_run:
            return
        try:
            self.mgr.resume(self.current_run)
        except Exception as e:
            QMessageBox.critical(self, "resume failed", str(e))

    # -- transcript --------------------------------------------------------------------
    def _fill_transcript(self):
        row = self.t_list.currentRow()
        self.t_list.blockSignals(True); self.t_list.clear()
        self._turns = self.mgr.transcript(self.current_run)
        for t in self._turns:
            n = len(t["samples"]) or 1
            broken = sum(1 for s in t["samples"] if s["mode"]) / n
            lab = (f"t{t['turn_idx']:3d} {t['phase']:7s} dose={t['step']:2d} "
                   f"{(t['request_id'] or ''):12s} broken={broken:.2f}"
                   + _attack_label(t["attack"]) + ("  [manual]" if t["intervention"] else ""))
            self.t_list.addItem(QListWidgetItem(lab))
        self.t_list.blockSignals(False)
        if self._turns:
            self.t_list.setCurrentRow(min(max(0, row), len(self._turns) - 1)
                                      if row >= 0 else len(self._turns) - 1)

    def _show_turn(self, row: int):
        if row < 0 or row >= len(self._turns):
            return
        t = self._turns[row]
        head = (f"<p><b>turn {t['turn_idx']}</b> phase={t['phase']} dose={t['step']} "
                f"request={t['request_id']} bridge={t['bridge_source']}")
        a = t["attack"]
        if a and a.get("kind") == "descent":
            head += (f"<br><b>descent step {a['step']}</b>: trait <i>{a['slot']}</i> flipped, "
                     f"{a['family']} intensity {a['intensity']} (cumulative {a.get('cumulative_intensity')}): "
                     f"<s>{html.escape(a['before'])}</s> &rarr; <b style='color:#e34948'>{html.escape(a['after'])}</b>"
                     f" &mdash; {html.escape(a.get('rationale', ''))}")
        elif a and a.get("kind") == "random":
            head += (f"<br><b>random message {a.get('random_idx')}</b>: {a['n_insults']} insulted "
                     f"({', '.join(a['insulted'])}); families {a.get('families')}; "
                     f"cumulative intensity {a.get('cumulative_intensity')}")
        head += "</p>"
        self.t_b.setHtml(head + _seg_html(t["segments"], self.dark))
        parts = []
        for s in t["samples"]:
            m = s["metrics"]
            mode = s["mode"] or "-"
            col = MODE_COLORS.get(s["mode"] or "", "#6b6b6b")
            cells = " ".join(f"{k.replace('_rate', '').replace('_present', '')}={_fmt(m.get(k))}" for k in HEADLINE)
            parts.append(f"<p><b style='color:{col}'>sample {s['sample_idx']} [{mode}]</b> seed={s['seed']}"
                         + (f" <span style='color:#e34948'>error: {html.escape(str(s['error']))}</span>" if s["error"] else "")
                         + f"<br><small>{cells}</small><br>{html.escape(s['text'] or '')}</p>")
        self.t_a.setHtml("".join(parts) or "<p>no samples</p>")

    # -- attacks -----------------------------------------------------------------------
    def _fill_attacks(self, *_):
        if not self.current_run:
            return
        atks = self.mgr.attacks(self.current_run)
        series = {r["turn_idx"]: r for r in analyze.series(self.mgr.store, self.current_run,
                                                            self.mgr.cfg.get("thresholds"))}
        traits = sorted({a["slot"] for a in atks if a["kind"] == "descent"})
        if self.a_slot.count() != len(traits) + 1:
            self.a_slot.blockSignals(True); self.a_slot.clear(); self.a_slot.addItem("all traits")
            self.a_slot.addItems(traits); self.a_slot.blockSignals(False)
        kind, fam = self.a_kind.currentText(), self.a_family.currentText()
        trait, mi = self.a_slot.currentText(), self.a_minint.value()
        rows = []
        for a in atks:
            if kind != "all" and a["kind"] != kind:
                continue
            if fam != "all" and a["family"] != fam:
                continue
            if trait != "all traits" and trait not in (a.get("insulted") or []):
                continue
            if mi and (a["intensity"] is None or a["intensity"] < mi):
                continue
            rows.append(a)
        self._attack_rows = rows
        self.a_table.setRowCount(len(rows))
        for i, a in enumerate(rows):
            br = series.get(a["turn_idx"], {}).get("frac_broken")
            vals = [a["kind"], a["idx"], a["turn_idx"], a["dose"], a["slot"], a["family"],
                    _fmt(a["intensity"]), a["cumulative_intensity"],
                    f"{a['before']} -> {a['after']}" if a["kind"] == "descent" else a["after"],
                    "yes" if a["played"] else "", _fmt(br)]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v)); it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if j == 5:
                    it.setForeground(QBrush(QColor(FAMILY_COLORS.get(a["family"], "#888888"))))
                self.a_table.setItem(i, j, it)

    def _selected_attack(self) -> dict | None:
        sm = self.a_table.selectionModel()
        rows = sm.selectedRows() if sm else []
        if not rows:
            return None
        return self._attack_rows[rows[0].row()]

    def _show_attack(self):
        a = self._selected_attack()
        if not a:
            return
        d = self.mgr.attack_detail(self.current_run, a["turn_idx"])
        if a["kind"] == "descent":
            before = html.escape(a["slot_before"]).replace(
                html.escape(a["before"]), f"<b style='color:#2a78d6'>{html.escape(a['before'])}</b>", 1)
            after = html.escape(a["slot_after"]).replace(
                html.escape(a["after"]), f"<b style='color:#e34948;background:#ffe9e9'>{html.escape(a['after'])}</b>", 1)
            out = [f"<h3>descent step {a['idx']} (turn {a['turn_idx']}, dose {a['dose']}) &mdash; trait "
                   f"<i>{a['slot']}</i>, {a['family']} intensity {a['intensity']} "
                   f"(cumulative {a['cumulative_intensity']})</h3>",
                   f"<p><i>{html.escape(a.get('rationale', ''))}</i></p>",
                   f"<p><b>praise:</b> {before}<br><b>insult:</b> {after}</p>",
                   f"<p><b>insulted so far:</b> {', '.join(a['insulted'])}</p>"]
        else:
            out = [f"<h3>random message {a['idx']} (turn {a['turn_idx']}) &mdash; dose {a['dose']} of "
                   f"{len(d['rendered'] or [])}, families {a.get('families')}, cumulative intensity "
                   f"{a['cumulative_intensity']}</h3>",
                   f"<p><b>insulted:</b> {', '.join(a['insulted']) or 'none'}</p>"]
        if d.get("rendered"):
            lines = []
            for s in d["rendered"]:
                txt = html.escape(s["text"])
                if s["insulted"] and s["after"]:
                    txt = txt.replace(html.escape(s["after"]),
                                      f"<b style='color:#e34948'>{html.escape(s['after'])}</b>", 1)
                mark = "&#9679;" if s["insulted"] else "&#9675;"
                lines.append(f"{mark} <small style='color:{FAMILY_COLORS.get(s['family'], '#888888')}'>{s['slot']}</small> {txt}")
            out.append("<p>" + "<br>".join(lines) + "</p>")
        if d["turn"]:
            out.append(f"<p><b>request:</b> {d['turn']['request_id']}  <b>bridge:</b> {d['turn']['bridge_source']}</p>")
            for s in d["samples"]:
                m = s["metrics"]; col = MODE_COLORS.get(s["mode"] or "", "#6b6b6b")
                out.append(f"<p><b style='color:{col}'>A sample {s['sample_idx']} [{s['mode'] or '-'}]</b> "
                           f"valence={_fmt(m.get('valence'))} abase={_fmt(m.get('self_abasement_rate'))} "
                           f"hostile={_fmt(m.get('counter_hostility_rate'))} boundary={_fmt(m.get('boundary_present'))} "
                           f"mirror={_fmt(m.get('mirroring'))} drift={_fmt(m.get('identity_drift'))} "
                           f"check={_fmt(m.get('check_score'))}<br>{html.escape(s['text'] or '')}</p>")
        else:
            out.append("<p><i>not played yet</i></p>")
        if d["canary"]:
            c = d["canary"]
            out.append(f"<p><b>nearest canary</b> (turn {c['turn_idx']}): fresh={_fmt(c.get('fresh'))} "
                       f"context={_fmt(c.get('context'))}</p>")
        if self.control_run:
            cd = self.mgr.attack_detail(self.control_run, a["turn_idx"])
            if cd["attack"]:
                n = len(cd["samples"]) or 1
                br = sum(1 for s in cd["samples"] if s["mode"]) / n
                out.append(f"<p><b>control at the same message:</b> {html.escape(cd['attack']['after'])}, "
                           f"broken {br:.2f}</p>")
        self.a_detail.setHtml("".join(out))

    def _jump_from_attack(self):
        a = self._selected_attack()
        if not a:
            return
        self.tabs.setCurrentIndex(1); self._fill_transcript()
        for i, t in enumerate(self._turns):
            if t["turn_idx"] == a["turn_idx"]:
                self.t_list.setCurrentRow(i); break

    def _reroll_attack(self):
        a = self._selected_attack()
        if a and a["played"]:
            self.mgr.reroll(self.current_run, a["turn_idx"], 1)
            QTimer.singleShot(500, self._show_attack)

    # -- script editor -------------------------------------------------------------------
    def _load_script(self):
        if self.current_run:
            self.s_edit.setPlainText(self.mgr.ladder_yaml(self.current_run))
            self.s_msg.setText("loaded latest revision")

    def _validate_script(self):
        try:
            l = Ladder.from_yaml(self.s_edit.toPlainText())
        except Exception as e:
            self.s_msg.setText(f"parse error: {e}"); return
        probs = l.validate()
        self.s_msg.setText("valid: %d traits, descent %d, random %d, sha %s"
                           % (l.n_slots, l.n_steps, l.n_random, l.sha256[:16]) if not probs
                           else "INVALID: " + " | ".join(probs[:6]))

    def _diff_script(self):
        old = self.mgr.ladder_yaml(self.current_run).splitlines()
        new = self.s_edit.toPlainText().splitlines()
        self.s_diff.setPlainText("\n".join(difflib.unified_diff(old, new, "current", "edited", lineterm="")) or "(no changes)")

    def _save_script(self):
        res = self.mgr.revise_ladder(self.current_run, self.s_edit.toPlainText())
        self.s_msg.setText(f"saved revision {res.get('rev')}" if res.get("ok") else f"rejected: {res.get('reason')}")
        if res.get("ok"):
            self._load_script(); self._fill_attacks()

    # -- intervene -------------------------------------------------------------------------
    def _manual_b(self):
        txt = self.i_text.toPlainText().strip()
        if txt and self.mgr.manual_b(self.current_run, txt):
            self.i_log.appendPlainText("queued manual B turn"); self.i_text.clear()
        else:
            self.i_log.appendPlainText("no active run to queue into")

    def _reroll(self):
        res = self.mgr.reroll(self.current_run, self.i_turn.value(), self.i_shift.value())
        self.i_log.appendPlainText(f"reroll turn {self.i_turn.value()}: "
                                   f"{'queued' if isinstance(res, dict) and res.get('queued') else 'done' if res else 'no such turn'}")

    def _fill_events(self):
        self.i_log.setPlainText("\n".join(f"{e['ts']}  {e['kind']}  {e['detail']}"
                                          for e in self.mgr.store.events(self.current_run)))

    # -- curves ---------------------------------------------------------------------------
    def _toggle_series(self, key, on):
        self.chart.show[key] = on; self.chart.update()

    def _fill_curves(self):
        rep = self.mgr.report(self.current_run)
        run = rep["run"]; offset = int(run.get("n_know") or 0) + int(run.get("n_praise") or 0)
        ctrl = analyze.series(self.mgr.store, self.control_run, self.mgr.cfg.get("thresholds")) if self.control_run else None
        self.chart.set_data(rep["series"], rep["endpoints"], rep["fit"], rep["canary"], offset,
                            rep.get("n_slots") or 15, ctrl)
        e, f, rn = rep["endpoints"], rep["fit"], rep["random"]
        self.c_summary.setText(
            f"descent: s50={_fmt(f.get('s50'))} slope={_fmt(f.get('slope'), 3)} density={_fmt(rep.get('density'), 4)} "
            f"s_tone={e.get('s_tone')} s_break={e.get('s_break')} ({e.get('mode_at_break')}) "
            f"s_collapse={e.get('s_collapse')} canary_fail={e.get('s_canary_fail')} confound={e.get('degradation_confound')}"
            f"  |  random: r50={_fmt(rn.get('r50'))} hysteresis={_fmt(rn.get('hysteresis'))} "
            f"scarring={_fmt(rn.get('scarring'), 3)} recovery={_fmt(rn.get('recovery'), 3)}  |  "
            + ("PUBLISHABLE" if rep["validity"]["publishable"] else "not publishable: " + ", ".join(rep["validity"]["blocking"])))

    # -- compare ----------------------------------------------------------------------------
    def _fill_compare(self):
        rows = self.mgr.compare([r["run_id"] for r in self.mgr.runs()])
        self._cmp_rows = rows
        self.cmp_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            s50 = "censored" if r["censored"] else _fmt(r["s50"])
            vals = [r["run_id"], r["run_name"], r["subject"], r.get("persona"), r["adversary"],
                    f"{r['ladder']}/{r['kind']}", r.get("ladder_set") or "none", r["status"], s50, _fmt(r["density"], 4),
                    r["s_break"], r["mode"], _fmt(r["r50"]), _fmt(r["scarring"], 3), r["confound"],
                    r["publishable"]]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v)); it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.cmp_table.setItem(i, j, it)
        profs = self.mgr.profiles()
        prow = []
        for pf in profs:
            for persona in ("narcissist", "psychopath", "machiavellian", "machiavellian_bundle"):
                e = pf["triangle"].get(persona) or {}
                if persona == "machiavellian_bundle" and e.get("run_id") is None:
                    continue
                if e.get("run_id") is None:
                    s50 = "no run"
                elif e.get("censored"):
                    s50 = "censored"
                else:
                    s50 = _fmt(e.get("s50"))
                ctrl = (e.get("control") or {}).get("difference")
                prow.append([pf["subject"], persona, s50, _fmt(e.get("density"), 3),
                             e.get("mode") or "-", _fmt(e.get("scarring"), 3), _fmt(ctrl)])
        self.prof_table.setRowCount(len(prow))
        for i, vals in enumerate(prow):
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v)); it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.prof_table.setItem(i, j, it)

    def _diff_runs(self):
        sm = self.cmp_table.selectionModel()
        sel = sorted({ix.row() for ix in sm.selectedRows()}) if sm else []
        if len(sel) != 2:
            self.cmp_msg.setText("select exactly two rows: a hostile run and its control"); return
        a, b = self._cmp_rows[sel[0]], self._cmp_rows[sel[1]]
        if a["kind"] == "control" and b["kind"] != "control":
            a, b = b, a
        d = analyze.control_difference(self.mgr.store, a["run_id"], b["run_id"], self.mgr.cfg)
        self.cmp_msg.setText(f"s50 hostile={d['s50_hostile']}  control={d['s50_control']}  "
                             f"difference={d['difference']}  |  scarring hostile={d['scarring_hostile']} "
                             f"control={d['scarring_control']} difference={d['scarring_difference']}  ({d['note']})")

    # -- label ---------------------------------------------------------------------------------
    def _draw_band_if_empty(self):
        if not self._band:
            self._draw_band()

    def _draw_band(self):
        self._band = self.mgr.band(self.current_run, 40); self._band_i = 0
        self._show_label_item()

    def _show_label_item(self):
        if not self._band or self._band_i >= len(self._band):
            self.l_info.setText("band exhausted; draw again or run more turns"); return
        r = self._band[self._band_i]
        self.l_info.setText(f"{self._band_i + 1}/{len(self._band)}  turn {r['turn_idx']} sample {r['sample_idx']} "
                            f"dose {r['step']}   (lexical says: {r['lexical_mode'] or 'none'})")
        self.l_b.setPlainText(r.get("b_text", "")); self.l_a.setPlainText(r["text"] or "")
        for b in self.l_group.buttons():
            b.setChecked(False)

    def _save_label(self):
        btn = self.l_group.checkedButton()
        if not btn or not self._band:
            return
        r = self._band[self._band_i]
        out = self.mgr.add_label(self.current_run, r["turn_idx"], r["sample_idx"], btn.text())
        self.l_kappa.setText(f"labels={out['n_labels']}  kappa vs lexical={out['kappa']}")
        self._next_label()

    def _next_label(self):
        self._band_i += 1; self._show_label_item()

    # -- report ------------------------------------------------------------------------------
    def _fill_report(self):
        self.r_text.setPlainText(self.mgr.report_text(
            self.current_run, ci=self.r_ci.isChecked(),
            show_trait_examples=self.r_examples.isChecked(), full=False))

    def _fill_full_report(self):
        self.r_text.setPlainText(self.mgr.report_text(
            self.current_run, ci=self.r_ci.isChecked(), show_trait_examples=True, full=True))

    def _recompute(self):
        n = self.mgr.recompute_metrics(self.current_run)
        self.r_text.appendPlainText(f"\nrecomputed {n} samples"); self._fill_report()

    # -- settings --------------------------------------------------------------------------------
    def _save_keys(self):
        vals = {}
        for env, e in self.k_edits.items():
            v = e.text()
            if v == "-":
                vals[env] = ""
            elif v:
                vals[env] = v
        self.mgr.save_credentials(vals)
        for e in self.k_edits.values():
            e.clear()
        for c in self.mgr.credential_status():
            self.k_edits[c["env"]].setPlaceholderText(c["masked"] or "not set")
        QMessageBox.information(self, "saved", f"{len(vals)} credential(s) updated")

    def _run_judge(self):
        kind = self.j_kind.currentText()
        self.mgr.cfg.setdefault("judge", {})["kind"] = kind
        key = "anthropic_model" if kind == "anthropic" else "local_model"
        self.mgr.cfg["judge"][key] = self.j_model.currentData()
        self.mgr.cfg["judge"]["n"] = self.j_n.value()
        if kind == "none":
            self.j_msg.setText("judge kind is none"); return
        try:
            out = self.mgr.judge(self.current_run, self.j_n.value())
        except Exception as e:
            self.j_msg.setText(f"judge failed: {e}"); return
        self.j_msg.setText(f"judge {out.get('judge')}: kappa vs lexical = {out.get('kappa')} on n={out.get('n')}")


def main(mgr: RunManager | None = None) -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = QApplication.instance() or QApplication(sys.argv)
    mgr = mgr or RunManager(root)
    win = Main(mgr, app)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
