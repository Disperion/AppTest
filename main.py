# -*- coding: utf-8 -*-
"""
main.py — Kivy-приложение мониторинга Home Assistant (CPU и RAM).
Графики на базе kivy_garden.graph, обновление в фоне через поток.
Сохраняет настройки в config.json.
"""

import os
import json
import threading
import time
import requests

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.gridlayout import GridLayout
from kivy.core.window import Window
from kivy.utils import platform

from kivy_garden.graph import Graph, LinePlot

# Настройки
UPDATE_INTERVAL = 2.0   # сек между опросами
HISTORY_LEN = 120       # точек в графике
CONFIG_FILE = "config.json"

# Путь для конфига: если на Android, используем текущую папку приложения
BASE_PATH = os.getcwd()
CONFIG_PATH = os.path.join(BASE_PATH, CONFIG_FILE)


def load_config():
    default = {
        "ha_url": "http://homeassistant.local:8123",
        "ha_token": "",
        "entity_cpu": "sensor.processor_temperature",
        "entity_ram": "sensor.memory_use_percent"
    }
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # fill defaults if missing
            for k, v in default.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception:
        pass
    return default


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


class SettingsPopup(Popup):
    def __init__(self, cfg, on_save_callback, **kwargs):
        super().__init__(**kwargs)
        self.title = "Настройки Home Assistant"
        self.size_hint = (0.9, 0.7)
        self.auto_dismiss = False

        self.cfg = cfg
        self.on_save_callback = on_save_callback

        layout = GridLayout(cols=1, padding=10, spacing=8)
        fields = [
            ("URL Home Assistant:", "ha_url"),
            ("Long-Lived Token:", "ha_token"),
            ("Entity CPU (entity_id):", "entity_cpu"),
            ("Entity RAM (entity_id):", "entity_ram"),
        ]
        self.entries = {}
        for label_text, key in fields:
            lbl = Label(text=label_text, size_hint_y=None, height=28, halign="left", valign="middle")
            lbl.text_size = (lbl.width, None)
            layout.add_widget(lbl)
            ent = TextInput(text=str(self.cfg.get(key, "")),
                            multiline=False,
                            size_hint_y=None, height=36)
            layout.add_widget(ent)
            self.entries[key] = ent

        btns = BoxLayout(size_hint_y=None, height=48, spacing=10)
        btn_check = Button(text="Проверить подключение", size_hint_x=0.6)
        btn_save = Button(text="Сохранить настройки", size_hint_x=0.4)
        btns.add_widget(btn_check)
        btns.add_widget(btn_save)
        layout.add_widget(btns)

        btn_close = Button(text="Закрыть", size_hint_y=None, height=40)
        layout.add_widget(btn_close)

        btn_check.bind(on_release=self.check_connection)
        btn_save.bind(on_release=self.save)
        btn_close.bind(on_release=lambda *a: self.dismiss())

        self.content = layout

    def check_connection(self, *a):
        temp_cfg = {k: self.entries[k].text.strip() for k in self.entries}
        url = temp_cfg.get("ha_url", "").rstrip("/")
        token = temp_cfg.get("ha_token", "").strip()
        if not url or not token:
            self._show_info("Ошибка", "Укажите URL и токен.")
            return
        try:
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(f"{url}/api/", headers=headers, timeout=6)
            if r.status_code == 200:
                self._show_info("Успех", "Подключение к Home Assistant установлено.")
            else:
                self._show_info("Ошибка", f"Ответ {r.status_code} — проверьте токен/URL.")
        except Exception as e:
            self._show_info("Ошибка", f"Не удалось подключиться: {e}")

    def save(self, *a):
        for k, ent in self.entries.items():
            self.cfg[k] = ent.text.strip()
        ok = save_config(self.cfg)
        if ok:
            if callable(self.on_save_callback):
                self.on_save_callback(self.cfg)
            self._show_info("Сохранено", "Настройки сохранены.")
            self.dismiss()
        else:
            self._show_info("Ошибка", "Не удалось сохранить настройки.")

    def _show_info(self, title, message):
        Popup(title=title, content=Label(text=message), size_hint=(0.6, 0.3)).open()


class MonitorRoot(FloatLayout):
    def __init__(self, cfg, **kwargs):
        super().__init__(**kwargs)
        Window.clearcolor = (0.118, 0.118, 0.118, 1)  # #1e1e1e
        self.cfg = cfg

        # top bar
        top = BoxLayout(size_hint=(1, 0.08), pos_hint={"top": 1}, padding=6)
        self.add_widget(top)
        lbl = Label(text="[b]Мониторинг сервера HA[/b]", markup=True, size_hint=(0.8, 1))
        top.add_widget(lbl)
        btn_settings = Button(text="⚙", size_hint=(0.06, 1))
        btn_settings.bind(on_release=self.open_settings)
        top.add_widget(btn_settings)
        self.status_label = Label(text="Отключено", size_hint=(0.14, 1), halign="right")
        top.add_widget(self.status_label)

        # main area: graphs (left large), small indicators on right (placed)
        main = BoxLayout(orientation="horizontal", pos_hint={"x": 0, "y": 0.08}, size_hint=(1, 0.84))
        self.add_widget(main)

        # left: graphs area (two stacked)
        graphs_box = BoxLayout(orientation="vertical", size_hint=(0.82, 1), padding=6, spacing=6)
        main.add_widget(graphs_box)

        # CPU Graph
        self.graph_cpu = Graph(xlabel='', ylabel='', x_ticks_minor=0,
                               x_ticks_major=5, y_ticks_major=10,
                               y_grid_label=True, x_grid_label=False,
                               padding=5, x_grid=True, y_grid=True, ymin=0, ymax=100,
                               background_color=[0.14, 0.14, 0.14, 1])
        self.graph_cpu.size_hint = (1, 0.5)
        graphs_box.add_widget(self.graph_cpu)
        self.plot_cpu = LinePlot(line_width=1.5, color=[0.0, 0.69, 0.94, 1])
        self.graph_cpu.add_plot(self.plot_cpu)

        # RAM Graph
        self.graph_ram = Graph(xlabel='', ylabel='', x_ticks_minor=0,
                               x_ticks_major=5, y_ticks_major=10,
                               y_grid_label=True, x_grid_label=False,
                               padding=5, x_grid=True, y_grid=True, ymin=0, ymax=100,
                               background_color=[0.14, 0.14, 0.14, 1])
        self.graph_ram.size_hint = (1, 0.5)
        graphs_box.add_widget(self.graph_ram)
        self.plot_ram = LinePlot(line_width=1.5, color=[0.0, 0.8, 0.4, 1])
        self.graph_ram.add_plot(self.plot_ram)

        # right side panel for current values and icons
        right_panel = BoxLayout(orientation="vertical", size_hint=(0.18, 1), padding=8, spacing=12)
        main.add_widget(right_panel)

        # CPU current value (icon above, value below)
        cpu_box = BoxLayout(orientation="vertical", size_hint=(1, 0.45), padding=6)
        right_panel.add_widget(cpu_box)
        cpu_icon_path = os.path.join(BASE_PATH, "icons", "cpu.png")
        if os.path.exists(cpu_icon_path):
            cpu_img = Image(source=cpu_icon_path, size_hint=(1, 0.6), allow_stretch=True, keep_ratio=True)
        else:
            cpu_img = Label(text="CPU", size_hint=(1, 0.6))
        cpu_box.add_widget(cpu_img)
        self.cpu_value_label = Label(text="—", size_hint=(1, 0.4))
        cpu_box.add_widget(self.cpu_value_label)

        # RAM current value
        ram_box = BoxLayout(orientation="vertical", size_hint=(1, 0.45), padding=6)
        right_panel.add_widget(ram_box)
        ram_icon_path = os.path.join(BASE_PATH, "icons", "ram.png")
        if os.path.exists(ram_icon_path):
            ram_img = Image(source=ram_icon_path, size_hint=(1, 0.6), allow_stretch=True, keep_ratio=True)
        else:
            ram_img = Label(text="RAM", size_hint=(1, 0.6))
        ram_box.add_widget(ram_img)
        self.ram_value_label = Label(text="—", size_hint=(1, 0.4))
        ram_box.add_widget(self.ram_value_label)

        # bottom bar (refresh button)
        bottom = BoxLayout(size_hint=(1, 0.08), pos_hint={"x": 0, "y": 0})
        self.add_widget(bottom)
        btn_refresh = Button(text="Обновить сейчас", size_hint=(0.2, 1))
        btn_refresh.bind(on_release=lambda *a: threading.Thread(target=self._do_update_once, daemon=True).start())
        bottom.add_widget(btn_refresh)
        self.last_update_label = Label(text="", size_hint=(0.8, 1))
        bottom.add_widget(self.last_update_label)

        # data containers
        self.cpu_history = []
        self.ram_history = []
        self.cpu_unit = ""
        self.ram_unit = ""

        # connection state
        self._set_status(False)

    def open_settings(self, *a):
        s = SettingsPopup(self.cfg, on_save_callback=self.on_settings_saved)
        s.open()

    def on_settings_saved(self, cfg):
        self.cfg = cfg
        self._set_status(False)

    def _set_status(self, ok: bool):
        self.status_label.text = "Подключено" if ok else "Отключено"
        self.status_label.color = (0, 1, 0, 1) if ok else (1, 0.5, 0, 1)

    def start_background(self):
        self._running = True
        self._bg_thread = threading.Thread(target=self._bg_loop, daemon=True)
        self._bg_thread.start()

    def stop_background(self):
        self._running = False

    def _bg_loop(self):
        while getattr(self, "_running", False):
            try:
                self._do_update_once()
            except Exception:
                pass
            time.sleep(UPDATE_INTERVAL)

    def _do_update_once(self):
        url = self.cfg.get("ha_url", "").rstrip("/")
        token = self.cfg.get("ha_token", "").strip()
        if not url or not token:
            Clock.schedule_once(lambda dt: self._set_status(False))
            return
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        # fetch cpu
        cpu_val, cpu_unit, _ = self._fetch_entity(url, headers, self.cfg.get("entity_cpu"))
        ram_val, ram_unit, _ = self._fetch_entity(url, headers, self.cfg.get("entity_ram"))
        ok = (cpu_val is not None) or (ram_val is not None)
        Clock.schedule_once(lambda dt: self._update_ui(cpu_val, cpu_unit, ram_val, ram_unit, ok))

    def _fetch_entity(self, base_url, headers, entity_id):
        try:
            if not entity_id:
                return None, "", {}
            r = requests.get(f"{base_url}/api/states/{entity_id}", headers=headers, timeout=6)
            if r.status_code == 200:
                data = r.json()
                state = data.get("state")
                attrs = data.get("attributes", {}) or {}
                unit = attrs.get("unit_of_measurement") or ""
                val = None
                try:
                    # try to parse float prefix
                    s = str(state).strip()
                    if s.lower() not in ("unknown", "unavailable", ""):
                        num = ""
                        for ch in s:
                            if ch.isdigit() or ch in ".-,":
                                num += ch
                            else:
                                break
                        if num:
                            val = float(num.replace(",", "."))
                except Exception:
                    val = None
                return val, unit, attrs
            return None, None, {}
        except Exception:
            return None, None, {}

    def _update_ui(self, cpu_val, cpu_unit, ram_val, ram_unit, ok):
        # update connection state
        self._set_status(ok)
        self.last_update_label.text = time.strftime("%Y-%m-%d %H:%M:%S")
        # CPU
        if cpu_val is not None:
            self.cpu_unit = cpu_unit or ""
            self.cpu_history.append(cpu_val)
            if len(self.cpu_history) > HISTORY_LEN:
                self.cpu_history.pop(0)
        if ram_val is not None:
            self.ram_unit = ram_unit or ""
            self.ram_history.append(ram_val)
            if len(self.ram_history) > HISTORY_LEN:
                self.ram_history.pop(0)

        # redraw plots
        try:
            if self.cpu_history:
                self.plot_cpu.points = [(i, v) for i, v in enumerate(self.cpu_history)]
                ymin = min(self.cpu_history) - 5
                ymax = max(self.cpu_history) + 5
                self.graph_cpu.ymin = ymin
                self.graph_cpu.ymax = ymax
            if self.ram_history:
                self.plot_ram.points = [(i, v) for i, v in enumerate(self.ram_history)]
                mn = min(self.ram_history); mx = max(self.ram_history)
                margin = max((mx - mn) * 0.1, 1.0)
                self.graph_ram.ymin = max(0, mn - margin)
                self.graph_ram.ymax = mx + margin
        except Exception:
            pass

        # current value labels (formatted)
        cpu_text = "—" if self.cpu_history == [] else f"{self.cpu_history[-1]:.1f} {self.cpu_unit}"
        ram_text = "—" if self.ram_history == [] else f"{self.ram_history[-1]:.1f} {self.ram_unit}"
        self.cpu_value_label.text = cpu_text
        self.ram_value_label.text = ram_text


class HAMonitorApp(App):
    def build(self):
        cfg = load_config()
        self.root_widget = MonitorRoot(cfg)
        # start background thread
        self.root_widget.start_background()
        return self.root_widget

    def on_stop(self):
        try:
            self.root_widget.stop_background()
        except Exception:
            pass


if __name__ == "__main__":
    HAMonitorApp().run()
