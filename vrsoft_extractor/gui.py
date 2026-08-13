from __future__ import annotations

import os
import queue
import json
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .settings import DEFAULT_BASE_URL, update_dotenv_file


APP_TITLE = "VRSoft Extractor"
DEFAULT_MAX_PAGES = 200
DEFAULT_CONCURRENCY = 2


@dataclass(frozen=True)
class GuiConfig:
    email: str = ""
    password: str = ""
    base_url: str = DEFAULT_BASE_URL
    max_pages: int = DEFAULT_MAX_PAGES
    concurrency: int = DEFAULT_CONCURRENCY


def project_dir_from_argv(argv: list[str] | None = None) -> Path:
    args = argv if argv is not None else sys.argv[1:]
    if "--project-dir" in args:
        index = args.index("--project-dir")
        if index + 1 < len(args):
            return Path(args[index + 1]).resolve()
    return Path.cwd().resolve()


def smoke_test_requested(argv: list[str] | None = None) -> bool:
    args = argv if argv is not None else sys.argv[1:]
    return "--smoke-test" in args


def read_env_file(path: Path) -> GuiConfig:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return GuiConfig(
        email=values.get("ENDOO_EMAIL", ""),
        password=values.get("ENDOO_PASSWORD", ""),
        base_url=values.get("ENDOO_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
        max_pages=_safe_int(values.get("ENDOO_MAX_PAGES"), DEFAULT_MAX_PAGES),
        concurrency=_safe_int(values.get("ENDOO_CONCURRENCY"), DEFAULT_CONCURRENCY),
    )


def write_env_file(path: Path, config: GuiConfig) -> None:
    update_dotenv_file(
        path,
        {
            "ENDOO_EMAIL": config.email,
            "ENDOO_PASSWORD": config.password,
            "ENDOO_BASE_URL": config.base_url,
            "ENDOO_MAX_PAGES": str(max(1, config.max_pages)),
            "ENDOO_CONCURRENCY": str(max(1, config.concurrency)),
        },
    )


def build_cli_command(
    project_dir: Path,
    action: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    max_pages: int = DEFAULT_MAX_PAGES,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[str]:
    exe = project_dir / ".venv" / "Scripts" / "vrsoft-extractor.exe"
    if exe.exists():
        command = [str(exe)]
    else:
        command = [sys.executable, "-m", "vrsoft_extractor"]

    command.extend(
        [
            "--project-dir",
            str(project_dir),
            "--base-url",
            base_url or DEFAULT_BASE_URL,
            "--max-pages",
            str(max_pages),
        ]
    )

    if action == "login":
        command.append("login")
    elif action == "scan":
        command.append("scan")
    elif action == "diagnostic-scan":
        command.extend(["scan", "--diagnostic"])
    elif action == "download":
        command.extend(["download", "--concurrency", str(concurrency)])
    elif action == "run":
        command.extend(["run", "--concurrency", str(concurrency)])
    else:
        raise ValueError(f"Acao desconhecida: {action}")
    return command


def read_inventory_count(project_dir: Path) -> int | None:
    inventory_path = project_dir / "metadata" / "videos.json"
    if not inventory_path.exists():
        return None
    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return len(data) if isinstance(data, list) else None


class ExtractorGui:
    def __init__(self, root: tk.Tk, project_dir: Path):
        self.root = root
        self.project_dir = project_dir.resolve()
        self.env_path = self.project_dir / ".env"
        self.process: subprocess.Popen[str] | None = None
        self.reader_thread: threading.Thread | None = None
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.current_action = tk.StringVar(value="Pronto")
        self.last_exit_code = tk.StringVar(value="Sem execucao")
        self.last_log = tk.StringVar(value="-")
        self.inventory_count = tk.StringVar(value="Inventario: nao encontrado")

        self.email_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.base_url_var = tk.StringVar(value=DEFAULT_BASE_URL)
        self.max_pages_var = tk.StringVar(value=str(DEFAULT_MAX_PAGES))
        self.concurrency_var = tk.StringVar(value=str(DEFAULT_CONCURRENCY))

        self.action_buttons: list[ttk.Button] = []
        self.stop_button: ttk.Button | None = None

        self.root.title(APP_TITLE)
        self.root.geometry("980x680")
        self.root.minsize(820, 560)
        self._build_layout()
        self._load_config()
        self._refresh_inventory_count()
        self._poll_output()

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        config_frame = ttk.LabelFrame(outer, text="Configuracao", padding=10)
        config_frame.grid(row=0, column=0, sticky="ew")
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)

        ttk.Label(config_frame, text="Email").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(config_frame, textvariable=self.email_var).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(config_frame, text="Senha").grid(row=0, column=2, sticky="w", padx=(12, 8), pady=4)
        ttk.Entry(config_frame, textvariable=self.password_var, show="*").grid(row=0, column=3, sticky="ew", pady=4)

        ttk.Label(config_frame, text="Base URL").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(config_frame, textvariable=self.base_url_var).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(config_frame, text="Max paginas").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=4)
        ttk.Spinbox(config_frame, from_=1, to=5000, textvariable=self.max_pages_var, width=10).grid(
            row=1,
            column=3,
            sticky="w",
            pady=4,
        )

        ttk.Label(config_frame, text="Concorrencia").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Spinbox(config_frame, from_=1, to=10, textvariable=self.concurrency_var, width=10).grid(
            row=2,
            column=1,
            sticky="w",
            pady=4,
        )

        ttk.Button(config_frame, text="Salvar .env", command=self.save_config).grid(
            row=2,
            column=3,
            sticky="e",
            pady=4,
        )

        actions_frame = ttk.Frame(outer)
        actions_frame.grid(row=1, column=0, sticky="ew", pady=(12, 8))
        for index in range(9):
            actions_frame.columnconfigure(index, weight=1)

        for index, (label, action) in enumerate(
            [
                ("Login", "login"),
                ("Scan", "scan"),
                ("Diagnostico Scan", "diagnostic-scan"),
                ("Download", "download"),
                ("Run", "run"),
            ]
        ):
            button = ttk.Button(actions_frame, text=label, command=lambda a=action: self.start_action(a))
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            self.action_buttons.append(button)

        self.stop_button = ttk.Button(actions_frame, text="Parar Processo", command=self.stop_process, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=5, sticky="ew", padx=(6, 0))

        ttk.Button(actions_frame, text="Abrir Downloads", command=lambda: self.open_folder("downloads")).grid(
            row=0,
            column=6,
            sticky="ew",
            padx=(6, 0),
        )
        ttk.Button(actions_frame, text="Abrir Metadata", command=lambda: self.open_folder("metadata")).grid(
            row=0,
            column=7,
            sticky="ew",
            padx=(6, 0),
        )
        ttk.Button(actions_frame, text="Abrir Logs", command=lambda: self.open_folder("logs")).grid(
            row=0,
            column=8,
            sticky="ew",
            padx=(6, 0),
        )

        log_frame = ttk.LabelFrame(outer, text="Logs", padding=8)
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=18, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        status_frame = ttk.Frame(outer)
        status_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        status_frame.columnconfigure(1, weight=1)
        status_frame.columnconfigure(3, weight=1)
        status_frame.columnconfigure(5, weight=1)
        ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.current_action).grid(row=0, column=1, sticky="w", padx=(4, 16))
        ttk.Label(status_frame, text="Saida:").grid(row=0, column=2, sticky="w")
        ttk.Label(status_frame, textvariable=self.last_exit_code).grid(row=0, column=3, sticky="w", padx=(4, 16))
        ttk.Label(status_frame, text="Ultimo log:").grid(row=0, column=4, sticky="w")
        ttk.Label(status_frame, textvariable=self.last_log).grid(row=0, column=5, sticky="w", padx=(4, 0))
        ttk.Label(status_frame, textvariable=self.inventory_count).grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))

    def _load_config(self) -> None:
        config = read_env_file(self.env_path)
        self.email_var.set(config.email)
        self.password_var.set(config.password)
        self.base_url_var.set(config.base_url)
        self.max_pages_var.set(str(config.max_pages))
        self.concurrency_var.set(str(config.concurrency))

    def _current_config(self) -> GuiConfig:
        return GuiConfig(
            email=self.email_var.get().strip(),
            password=self.password_var.get(),
            base_url=self.base_url_var.get().strip() or DEFAULT_BASE_URL,
            max_pages=_safe_int(self.max_pages_var.get(), DEFAULT_MAX_PAGES),
            concurrency=_safe_int(self.concurrency_var.get(), DEFAULT_CONCURRENCY),
        )

    def save_config(self) -> None:
        write_env_file(self.env_path, self._current_config())
        self._append_log("Configuracao salva em .env\n")

    def start_action(self, action: str) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning(APP_TITLE, "Ja existe um processo em execucao.")
            return
        if action == "download" and not self._inventory_has_videos():
            messagebox.showwarning(
                APP_TITLE,
                "O inventario esta vazio ou ausente. Execute Scan ou Diagnostico Scan antes do Download.",
            )
            self._append_log("Download bloqueado: inventario vazio ou ausente.\n")
            self._refresh_inventory_count()
            return

        config = self._current_config()
        write_env_file(self.env_path, config)
        command = build_cli_command(
            self.project_dir,
            action,
            base_url=config.base_url,
            max_pages=config.max_pages,
            concurrency=config.concurrency,
        )

        self._set_running(True)
        self.current_action.set(action)
        self.last_exit_code.set("Rodando")
        self._append_log(f"\n> Iniciando {action}\n")
        self._append_log("> " + self._redact(" ".join(command)) + "\n")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["ENDOO_EMAIL"] = config.email
        env["ENDOO_PASSWORD"] = config.password
        env["ENDOO_GUI_MODE"] = "1"

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(self.project_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                startupinfo=startupinfo,
            )
        except Exception as exc:
            self.process = None
            self._set_running(False)
            self.current_action.set("Erro")
            self.last_exit_code.set("Falha ao iniciar")
            self._append_log(f"Falha ao iniciar processo: {exc}\n")
            return

        self.reader_thread = threading.Thread(target=self._read_process_output, daemon=True)
        self.reader_thread.start()
        self.root.after(500, self._check_process)

    def stop_process(self) -> None:
        if not self.process or self.process.poll() is not None:
            self._append_log("Nenhum processo em execucao.\n")
            return
        self._append_log("Encerrando processo atual...\n")
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                self.process.terminate()
            self.root.after(3000, self._kill_if_needed)
        except Exception as exc:
            self._append_log(f"Falha ao encerrar processo: {exc}\n")

    def open_folder(self, name: str) -> None:
        target = self.project_dir / name
        target.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            filedialog.askdirectory(initialdir=str(target))

    def _read_process_output(self) -> None:
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self.output_queue.put(self._redact(line))

    def _poll_output(self) -> None:
        while True:
            try:
                line = self.output_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
            if "Log:" in line:
                self.last_log.set(line.split("Log:", 1)[1].strip())
        self.root.after(150, self._poll_output)

    def _check_process(self) -> None:
        if not self.process:
            return
        code = self.process.poll()
        if code is None:
            self.root.after(500, self._check_process)
            return
        self._append_log(f"Processo finalizado com codigo {code}\n")
        self.last_exit_code.set(str(code))
        self.current_action.set("Pronto" if code == 0 else "Finalizado com erro")
        self._refresh_inventory_count()
        self._set_running(False)
        self.process = None

    def _kill_if_needed(self) -> None:
        if self.process and self.process.poll() is None:
            self._append_log("Forcando encerramento do processo atual...\n")
            self.process.kill()

    def _set_running(self, running: bool) -> None:
        for button in self.action_buttons:
            button.configure(state=tk.DISABLED if running else tk.NORMAL)
        if self.stop_button:
            self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _inventory_has_videos(self) -> bool:
        count = read_inventory_count(self.project_dir)
        return bool(count and count > 0)

    def _refresh_inventory_count(self) -> None:
        count = read_inventory_count(self.project_dir)
        if count is None:
            self.inventory_count.set("Inventario: nao encontrado")
        else:
            self.inventory_count.set(f"Inventario: {count} video(s)")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, self._redact(text))
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _redact(self, text: str) -> str:
        password = self.password_var.get()
        email = self.email_var.get()
        if password:
            text = text.replace(password, "***")
        if email:
            text = text.replace(email, "***")
        return text


def _safe_int(value: object, fallback: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def main(argv: list[str] | None = None) -> int:
    project_dir = project_dir_from_argv(argv)
    root = tk.Tk()
    if smoke_test_requested(argv):
        root.withdraw()
    ExtractorGui(root, project_dir)
    if smoke_test_requested(argv):
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
