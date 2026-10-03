"""Windows launcher for the portable Hotspot Logger package."""
import json
import os
from pathlib import Path
import queue
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


APP_FOLDER = "Hotspot Logger"
LAUNCHER_SETTINGS = "windows-settings.json"
STARTUP_VALUE = "Hotspot Logger"
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def data_directory(environment=None, home=None):
    environment = os.environ if environment is None else environment
    base = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
    return Path(base) / APP_FOLDER if base else Path(home or Path.home()) / APP_FOLDER


def load_launcher_settings(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"lan_access": value.get("lan_access") is True}
    except (OSError, ValueError, TypeError):
        return {"lan_access": False}


def save_launcher_settings(path, settings):
    Path(path).write_text(json.dumps({"lan_access": settings.get("lan_access") is True}, indent=2) + "\n",
                          encoding="utf-8")


def startup_command(executable=None, script=None, frozen=None):
    executable = Path(executable) if executable is not None else Path(sys.executable).resolve()
    script = Path(script) if script is not None else Path(__file__).resolve()
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        return f'"{executable}" --startup'
    return f'"{executable}" "{script}" --startup'


def startup_enabled(registry=None):
    if os.name != "nt" and registry is None:
        return False
    if registry is None:
        import winreg as registry
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            value, _ = registry.QueryValueEx(key, STARTUP_VALUE)
        return value == startup_command()
    except OSError:
        return False


def set_startup_enabled(enabled, registry=None):
    if os.name != "nt" and registry is None:
        raise OSError("Windows startup settings are available only on Windows")
    if registry is None:
        import winreg as registry
    if enabled:
        with registry.CreateKey(registry.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            registry.SetValueEx(key, STARTUP_VALUE, 0, registry.REG_SZ, startup_command())
        return
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, STARTUP_KEY, 0,
                              registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE) as key:
            registry.DeleteValue(key, STARTUP_VALUE)
    except FileNotFoundError:
        pass


def lan_addresses():
    addresses = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = result[4][0]
            if not address.startswith("127.") and address != "0.0.0.0":
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


class LoggerServer:
    def __init__(self, application, port=8787):
        self.application = application
        self.port = port
        self.httpd = None
        self.thread = None
        self.poll_started = False

    def start(self, lan_access=False):
        if self.httpd is not None:
            return
        if not self.poll_started:
            self.application.init_db()
            threading.Thread(target=self.application.poll_loop, daemon=True,
                             name="HotspotLoggerPoll").start()
            self.poll_started = True
        host = "0.0.0.0" if lan_access else "127.0.0.1"
        self.httpd = self.application.ThreadingHTTPServer((host, self.port), self.application.Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True,
                                       name="HotspotLoggerWeb")
        self.thread.start()

    def stop(self):
        server, self.httpd = self.httpd, None
        if server is not None:
            server.shutdown()
            server.server_close()
        self.thread = None

    def restart(self, lan_access=False):
        self.stop()
        self.start(lan_access)


def is_hotspot_logger_running(url):
    try:
        with urllib.request.urlopen(url + "/healthz", timeout=2) as response:
            payload = json.loads(response.read(4096))
        return isinstance(payload, dict) and "version" in payload
    except (OSError, ValueError, urllib.error.URLError):
        return False


def configure_runtime():
    folder = data_directory()
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["DB_PATH"] = str(folder / "logger.sqlite")
    os.environ.setdefault("PORT", "8787")
    return folder


def run_headless_smoke(server, seconds=30):
    server.start(False)
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.25)
    finally:
        server.stop()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    folder = configure_runtime()
    log = open(folder / "hotspot-logger.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    import app

    port = int(os.environ["PORT"])
    url = f"http://127.0.0.1:{port}"
    server = LoggerServer(app, port)
    if "--headless-smoke" in argv:
        run_headless_smoke(server)
        return 0

    import tkinter as tk
    from tkinter import messagebox
    from PIL import Image
    import pystray

    settings_path = folder / LAUNCHER_SETTINGS
    settings = load_launcher_settings(settings_path)
    try:
        server.start(settings["lan_access"])
    except OSError as error:
        if is_hotspot_logger_running(url):
            webbrowser.open(url)
            messagebox.showinfo("Hotspot Logger", "Hotspot Logger is already running. Its page has been opened.")
            return 0
        messagebox.showerror("Hotspot Logger", f"Port {port} is already in use.\n\n{error}")
        return 1

    root = tk.Tk()
    root.title(f"Hotspot Logger {app.VERSION}")
    root.geometry("600x430")
    root.minsize(540, 400)
    root.configure(bg="#f4f7fa")

    icon_path = Path(app.__file__).resolve().parent / "assets" / "hotspot-logger-icon.png"
    try:
        root._brand_icon = tk.PhotoImage(file=str(icon_path))
        root.iconphoto(True, root._brand_icon)
    except tk.TclError:
        pass

    frame = tk.Frame(root, bg="#f4f7fa", padx=32, pady=28)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="Hotspot Logger", bg="#f4f7fa", fg="#063468",
             font=("Segoe UI", 24, "bold")).pack(anchor="w")
    tk.Label(frame, text="Created by KF0WSS", bg="#f4f7fa", fg="#3a536c",
             font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 20))
    status = tk.StringVar(value=f"Running on this computer: {url}")
    network = tk.StringVar()
    tk.Label(frame, textvariable=status, bg="#f4f7fa", fg="#172b3d",
             font=("Segoe UI", 11)).pack(anchor="w")
    tk.Label(frame, textvariable=network, bg="#f4f7fa", fg="#52677a",
             font=("Segoe UI", 10), wraplength=490, justify="left").pack(anchor="w", pady=(4, 18))

    lan_value = tk.BooleanVar(value=settings["lan_access"])
    startup_value = tk.BooleanVar(value=startup_enabled())
    startup_status = tk.StringVar(value="")

    def refresh_network_text():
        if lan_value.get():
            addresses = [f"http://{address}:{port}" for address in lan_addresses()]
            network.set("Trusted-LAN access is on. " + ("Other devices can use: " + ", ".join(addresses)
                        if addresses else "Use this PC's LAN address from another device."))
        else:
            network.set("Other devices cannot connect. This is the safest default for a Windows PC.")

    refresh_network_text()
    tk.Checkbutton(frame, text="Allow other devices on my trusted network", variable=lan_value,
                   bg="#f4f7fa", fg="#172b3d", activebackground="#f4f7fa",
                   font=("Segoe UI", 10)).pack(anchor="w")
    tk.Checkbutton(frame, text="Start Hotspot Logger when I sign in to Windows",
                   variable=startup_value, bg="#f4f7fa", fg="#172b3d",
                   activebackground="#f4f7fa", font=("Segoe UI", 10)).pack(anchor="w", pady=(5, 0))
    tk.Label(frame, textvariable=startup_status, bg="#f4f7fa", fg="#52677a",
             font=("Segoe UI", 9)).pack(anchor="w")

    def apply_network_setting():
        previous = settings["lan_access"]
        desired = lan_value.get()
        try:
            server.restart(desired)
            settings["lan_access"] = desired
            save_launcher_settings(settings_path, settings)
            refresh_network_text()
        except OSError as error:
            lan_value.set(previous)
            try:
                server.start(previous)
            except OSError:
                status.set("Stopped: port is unavailable")
            messagebox.showerror("Hotspot Logger", f"Could not change the network setting.\n\n{error}")

    def apply_startup_setting():
        previous = startup_enabled()
        desired = startup_value.get()
        try:
            set_startup_enabled(desired)
            startup_status.set("Windows startup is on." if desired else "Windows startup is off.")
        except OSError as error:
            startup_value.set(previous)
            startup_status.set("")
            messagebox.showerror("Hotspot Logger", f"Could not change the Windows startup setting.\n\n{error}")

    controls = tk.Frame(frame, bg="#f4f7fa")
    controls.pack(anchor="w", pady=(16, 0))
    button_options = dict(font=("Segoe UI", 10), padx=13, pady=7)
    tk.Button(controls, text="Open Logger", command=lambda: webbrowser.open(url), **button_options).pack(side="left")
    tk.Button(controls, text="Apply network setting", command=apply_network_setting,
              **button_options).pack(side="left", padx=8)
    tk.Button(controls, text="Open data folder", command=lambda: os.startfile(folder),
              **button_options).pack(side="left")

    tk.Button(frame, text="Apply Windows startup setting", command=apply_startup_setting,
              **button_options).pack(anchor="w", pady=(9, 0))

    actions = queue.Queue()
    stopping = False
    hide_notice_shown = False

    def show_window():
        root.deiconify()
        root.lift()
        root.focus_force()

    def hide_window():
        nonlocal hide_notice_shown
        root.withdraw()
        if not hide_notice_shown:
            hide_notice_shown = True
            try:
                tray.notify("Hotspot Logger is still running. Use the icon beside the clock to reopen or exit.",
                            "Hotspot Logger")
            except NotImplementedError:
                pass

    def restart_server():
        status.set("Restarting…")
        root.update_idletasks()
        try:
            server.restart(settings["lan_access"])
            status.set(f"Running on this computer: {url}")
        except OSError as error:
            status.set("Stopped: port is unavailable")
            messagebox.showerror("Hotspot Logger", f"Could not restart the logger.\n\n{error}")

    def request(action):
        actions.put(action)

    with Image.open(icon_path) as icon_image:
        tray_image = icon_image.copy()
    tray = pystray.Icon(
        "HotspotLogger",
        tray_image,
        "Hotspot Logger",
        menu=pystray.Menu(
            pystray.MenuItem("Open Logger", lambda _icon, _item: request("open"), default=True),
            pystray.MenuItem("Show controls", lambda _icon, _item: request("show")),
            pystray.MenuItem("Restart", lambda _icon, _item: request("restart")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda _icon, _item: request("exit")),
        ),
    )

    def close():
        nonlocal stopping
        if stopping:
            return
        stopping = True
        status.set("Stopping…")
        root.update_idletasks()
        tray.stop()
        server.stop()
        root.destroy()

    def process_actions():
        try:
            while True:
                action = actions.get_nowait()
                if action == "open":
                    webbrowser.open(url)
                elif action == "show":
                    show_window()
                elif action == "restart":
                    restart_server()
                elif action == "exit":
                    close()
                    return
        except queue.Empty:
            pass
        root.after(100, process_actions)

    root.protocol("WM_DELETE_WINDOW", hide_window)
    tk.Label(frame, text="Closing this window keeps Hotspot Logger running beside the clock. Use the tray icon to reopen or exit.",
             bg="#f4f7fa", fg="#52677a", font=("Segoe UI", 9)).pack(anchor="w", pady=(22, 0))
    tray.run_detached()
    process_actions()
    if "--startup" in argv:
        root.withdraw()
    else:
        root.after(600, lambda: webbrowser.open(url))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
