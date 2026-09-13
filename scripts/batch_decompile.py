"""Função e script utilitário para descompilação de arquivos JAR em lote.

Permite selecionar múltiplos arquivos JAR via interface gráfica nativa (ou linha de comando/código)
e descompilar todos em lote utilizando a toolchain isolada (Java 17 + Vineflower / CFR) do VRStudio.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

# Garante suporte a UTF-8 no console Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Garante que o diretório raiz do projeto esteja no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vrsoft_extractor.mary.jvm_toolchain import (  # noqa: E402
    DecompileRequest,
    DecompileResult,
    JvmToolchain,
)
from vrsoft_extractor.mary.code_processing_hardware import detect_code_processing_hardware  # noqa: E402


@dataclass
class JarDecompileResult:
    jar_path: Path
    jar_name: str
    output_dir: Path
    status: str  # "completed", "failed", "skipped"
    decompiler_used: str
    duration_ms: int
    source_files_count: int
    error: str = ""


def select_jars_dialog(initial_dir: str | Path | None = None) -> list[Path]:
    """Abre caixa de diálogo nativa para seleção múltipla de arquivos .jar."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        start_dir = (
            str(Path(initial_dir).resolve())
            if initial_dir
            else str(PROJECT_ROOT / "VRProject" / "ERP" / "releases")
        )
        if not os.path.isdir(start_dir):
            start_dir = str(PROJECT_ROOT)

        selected = filedialog.askopenfilenames(
            title="Selecione os arquivos JAR para descompilar",
            initialdir=start_dir,
            filetypes=[("Arquivos JAR (*.jar)", "*.jar"), ("Todos os arquivos (*.*)", "*.*")],
        )
        root.destroy()
        return [Path(p).resolve() for p in selected if p.endswith(".jar") or Path(p).is_file()]
    except Exception as exc:
        print(f"[Aviso] Não foi possível abrir diálogo gráfico: {exc}")
        return []


def select_output_dir_dialog(initial_dir: str | Path | None = None) -> Path | None:
    """Abre caixa de diálogo nativa para escolher o diretório de destino."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        start_dir = (
            str(Path(initial_dir).resolve())
            if initial_dir
            else str(PROJECT_ROOT / "VRProject" / "ERP" / "decompilados")
        )
        selected = filedialog.askdirectory(
            title="Selecione a pasta de destino para o código descompilado",
            initialdir=start_dir,
        )
        root.destroy()
        return Path(selected).resolve() if selected else None
    except Exception as exc:
        print(f"[Aviso] Não foi possível abrir diálogo de pasta: {exc}")
        return None


def count_source_files(directory: Path) -> int:
    """Conta a quantidade de arquivos .java gerados no diretório de saída."""
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.rglob("*.java") if p.is_file())


def decompile_single_jar(
    jar_path: Path,
    output_base_dir: Path,
    toolchain: JvmToolchain,
    *,
    preferred_decompiler: str = "auto",
    heap_mb: int = 2048,
    timeout_seconds: int = 600,
    max_cpu_cores: int = 2,
    log_callback: Callable[[str], None] | None = None,
) -> JarDecompileResult:
    """Descompila um único arquivo JAR para uma subpasta em output_base_dir.
    
    Tenta o descompilador preferido (Vineflower por padrão).
    Em caso de falha, tenta o secundário (CFR) como fallback.
    """
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    jar_path = Path(jar_path).resolve()
    if not jar_path.is_file():
        return JarDecompileResult(
            jar_path=jar_path,
            jar_name=jar_path.name,
            output_dir=output_base_dir / jar_path.stem,
            status="failed",
            decompiler_used="none",
            duration_ms=0,
            source_files_count=0,
            error=f"Arquivo JAR não encontrado: {jar_path}",
        )

    output_base_dir.mkdir(parents=True, exist_ok=True)
    # Separate equal basenames, retries and pre-existing user output.
    target_dir = Path(tempfile.mkdtemp(prefix=f"{jar_path.stem}-", dir=output_base_dir))

    adapters = toolchain.adapters()
    adapter_map = {adapter.name: adapter for adapter in adapters}

    # Ordem dos decompiladores a testar
    if preferred_decompiler == "cfr":
        order = ["cfr", "vineflower"]
    elif preferred_decompiler == "vineflower":
        order = ["vineflower", "cfr"]
    else:  # "auto"
        order = ["vineflower", "cfr"]

    last_error = ""
    started_total = time.monotonic()
    
    for tool_name in order:
        adapter = adapter_map.get(tool_name)
        if not adapter:
            continue
        
        status = adapter.status()
        if not status.available:
            last_error = f"{tool_name} indisponível: {status.error}"
            continue

        log(f"  -> [{jar_path.name}] Descompilando com {tool_name}...")
        attempt_dir = target_dir / tool_name
        req = DecompileRequest(
            input_path=jar_path,
            output_dir=attempt_dir,
            timeout_seconds=timeout_seconds,
            max_heap_mb=heap_mb,
            max_cpu_cores=max_cpu_cores,
            process_priority="low",
        )
        res: DecompileResult = adapter.decompile(req)
        
        source_count = count_source_files(attempt_dir)
        if res.status == "completed" and source_count > 0:
            total_duration = int((time.monotonic() - started_total) * 1000)
            return JarDecompileResult(
                jar_path=jar_path,
                jar_name=jar_path.name,
                output_dir=attempt_dir,
                status="completed",
                decompiler_used=tool_name,
                duration_ms=total_duration,
                source_files_count=source_count,
            )
        else:
            last_error = res.error or f"Falha no processo (exit_code={res.exit_code})"
            log(f"  [!] {tool_name} falhou em {jar_path.name}: {last_error}. Tentando fallback se houver...")

    total_duration = int((time.monotonic() - started_total) * 1000)
    source_count = count_source_files(target_dir)
    return JarDecompileResult(
        jar_path=jar_path,
        jar_name=jar_path.name,
        output_dir=target_dir,
        status="failed",
        decompiler_used="fallback_failed",
        duration_ms=total_duration,
        source_files_count=source_count,
        error=last_error or "Nenhum descompilador disponível.",
    )


def decompile_jars(
    jar_paths: Sequence[str | Path],
    output_dir: str | Path,
    *,
    project_root: str | Path | None = None,
    max_workers: int = 2,
    max_cpu_cores: int | None = None,
    heap_mb: int = 2048,
    timeout_seconds: int = 600,
    preferred_decompiler: str = "auto",
    progress_callback: Callable[[int, int, JarDecompileResult], None] | None = None,
) -> dict[str, object]:
    """Descompila uma lista de arquivos JAR em lote.

    Args:
        jar_paths: Lista ou tupla de caminhos para os arquivos .jar.
        output_dir: Pasta raiz onde cada JAR terá sua subpasta com os fontes .java.
        project_root: Diretório raiz do VRStudio (onde estão as ferramentas java17 e decompiladores).
        max_workers: Quantidade de descompilações paralelas simultâneas.
        heap_mb: Memória máxima heap Java por processo (em MB).
        timeout_seconds: Tempo limite em segundos por arquivo JAR.
        preferred_decompiler: "auto", "vineflower" ou "cfr".
        progress_callback: Função chamada a cada JAR concluído: fn(concluidos, total, resultado).

    Returns:
        Dicionário com estatísticas completas e lista de resultados.
    """
    root = Path(project_root or (PROJECT_ROOT / "VRProject")).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    jars = [Path(p).resolve() for p in jar_paths if str(p).strip()]
    if not jars:
        return {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "output_dir": str(out_dir),
            "results": [],
        }

    toolchain = JvmToolchain(root)
    doctor = toolchain.doctor()
    if not doctor.get("ready"):
        print("[Aviso] Toolchain JVM não totalmente validada:")
        for k in ("java", "vineflower", "cfr"):
            info = doctor.get(k, {})
            if not info.get("available"):
                print(f"  - {k}: {info.get('error', 'indisponível')}")

    total = len(jars)
    hardware = detect_code_processing_hardware()
    cpu_cores = max(1, min(max_cpu_cores or hardware.recommended_cpu_cores, hardware.logical_cpu_count))
    workers = min(max(1, max_workers), total, hardware.parallel_workers_for(cpu_cores, heap_mb))
    cores_per_worker = max(1, cpu_cores // workers)
    print("\n=======================================================")
    print(f" Iniciando Descompilacao em Lote de {total} JAR(s)")
    print(f" Destino: {out_dir}")
    print(f" Concorrencia: {workers} workers paralelos | Heap: {heap_mb}MB")
    print("=======================================================\n")

    results: list[JarDecompileResult] = []
    completed_count = 0
    started_time = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="jar-decompile") as pool:
        future_to_jar = {
            pool.submit(
                decompile_single_jar,
                jar,
                out_dir,
                toolchain,
                preferred_decompiler=preferred_decompiler,
                heap_mb=heap_mb,
                timeout_seconds=timeout_seconds,
                max_cpu_cores=cores_per_worker,
            ): jar
            for jar in jars
        }

        for future in as_completed(future_to_jar):
            jar = future_to_jar[future]
            try:
                res = future.result()
            except Exception as exc:
                res = JarDecompileResult(
                    jar_path=jar,
                    jar_name=jar.name,
                    output_dir=out_dir / jar.stem,
                    status="failed",
                    decompiler_used="error",
                    duration_ms=0,
                    source_files_count=0,
                    error=str(exc),
                )
            results.append(res)
            completed_count += 1

            tag = "[OK]" if res.status == "completed" else "[FALHA]"
            dur_s = res.duration_ms / 1000.0
            print(
                f"[{completed_count}/{total}] {tag} {res.jar_name}: "
                f"{res.status.upper()} ({res.source_files_count} arquivos .java, "
                f"{dur_s:.1f}s via {res.decompiler_used})"
            )
            if res.error:
                print(f"       Erro: {res.error}")

            if progress_callback:
                progress_callback(completed_count, total, res)

    total_duration_s = time.monotonic() - started_time
    succeeded = sum(1 for r in results if r.status == "completed")
    failed = total - succeeded
    total_sources = sum(r.source_files_count for r in results)

    print("\n=======================================================")
    print(f" Processamento Concluido em {total_duration_s:.1f}s")
    print(f" Sucesso: {succeeded}/{total} JARs")
    if failed > 0:
        print(f" Falhas: {failed} JARs")
    print(f" Total de fontes Java gerados: {total_sources}")
    print(f" Diretorio final: {out_dir}")
    print("=======================================================\n")

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "total_source_files": total_sources,
        "total_duration_seconds": round(total_duration_s, 2),
        "output_dir": str(out_dir),
        "results": [
            {
                "jar_name": r.jar_name,
                "jar_path": str(r.jar_path),
                "output_dir": str(r.output_dir),
                "status": r.status,
                "decompiler": r.decompiler_used,
                "duration_ms": r.duration_ms,
                "source_files": r.source_files_count,
                "error": r.error,
            }
            for r in results
        ],
    }


def load_global_decompile_config(preferences=None) -> dict[str, int]:
    """Carrega a configuracao global de descompilacao salva nas preferencias do VRStudio."""
    config = {
        "heap_mb": 2048,
        "timeout_seconds": 600,
        "max_workers": 2,
        "max_cpu_cores": detect_code_processing_hardware().recommended_cpu_cores,
    }
    try:
        from PySide6.QtCore import QSettings
        from vrsoft_extractor.mary.brand import ORGANIZATION_NAME, SETTINGS_APP_NAME

        pref = preferences or QSettings(ORGANIZATION_NAME, SETTINGS_APP_NAME)
        h = pref.value("code_processing/max_heap_mb")
        if h is not None:
            config["heap_mb"] = int(h)
        t = pref.value("code_processing/timeout_seconds")
        if t is not None:
            config["timeout_seconds"] = int(t)
        w = pref.value("code_processing/max_cpu_cores")
        if w is not None:
            config["max_cpu_cores"] = max(1, int(w))
    except Exception:
        pass
    config["max_workers"] = detect_code_processing_hardware().parallel_workers_for(
        config["max_cpu_cores"], config["heap_mb"]
    )
    return config


def batch_decompile_interactive(
    initial_dir: str | Path | None = None,
    default_output_dir: str | Path | None = None,
    max_workers: int = 2,
    heap_mb: int = 2048,
    timeout_seconds: int = 600,
    preferred_decompiler: str = "auto",
    max_cpu_cores: int | None = None,
) -> dict[str, object] | None:
    """Modo interativo: abre selecao grafica para escolher os JARs e a pasta de destino,
    e inicia a descompilacao automaticamente respeitando os limites globais de JVM e hardware.
    """
    print("Abrindo janela para selecao dos arquivos JAR...")
    jars = select_jars_dialog(initial_dir)
    if not jars:
        print("Nenhum arquivo JAR foi selecionado. Operacao cancelada.")
        return None

    print(f"\n{len(jars)} arquivo(s) JAR selecionado(s):")
    for j in jars:
        print(f"  - {j.name}")

    out_dir = default_output_dir
    if not out_dir:
        print("\nAbrindo janela para selecao da pasta de destino...")
        out_dir = select_output_dir_dialog(PROJECT_ROOT / "VRProject" / "ERP" / "decompilados")
        if not out_dir:
            print("Seleção de destino cancelada.")
            return None

    return decompile_jars(
        jar_paths=jars,
        output_dir=out_dir,
        project_root=PROJECT_ROOT / "VRProject",
        max_workers=max_workers,
        max_cpu_cores=max_cpu_cores,
        heap_mb=heap_mb,
        timeout_seconds=timeout_seconds,
        preferred_decompiler=preferred_decompiler,
    )


def main() -> int:
    global_cfg = load_global_decompile_config()
    parser = argparse.ArgumentParser(
        description="Descompila arquivos JAR em lote usando Java 17 e Vineflower/CFR."
    )
    parser.add_argument(
        "--jars",
        nargs="*",
        help="Caminhos dos arquivos .jar a descompilar. Se omitido, abre seletor grafico de arquivos.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Diretorio onde as pastas com codigo descompilado serao salvas.",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=global_cfg["max_workers"],
        help=f"Quantidade de tarefas concorrentes em paralelo (padrao global: {global_cfg['max_workers']}).",
    )
    parser.add_argument(
        "--heap-mb",
        type=int,
        default=global_cfg["heap_mb"],
        help=f"Limite de heap Java em MB por processo (padrao global: {global_cfg['heap_mb']}).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=global_cfg["timeout_seconds"],
        help=f"Timeout em segundos por JAR (padrao global: {global_cfg['timeout_seconds']}).",
    )
    parser.add_argument(
        "--decompiler",
        choices=["auto", "vineflower", "cfr"],
        default="auto",
        help="Decompilador prioritario (padrao: auto).",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Forca abertura do seletor grafico de arquivos mesmo se parametros forem passados.",
    )

    args = parser.parse_args()

    if args.interactive or not args.jars:
        result = batch_decompile_interactive(
            default_output_dir=args.output_dir,
            max_workers=args.workers,
            max_cpu_cores=global_cfg["max_cpu_cores"],
            heap_mb=args.heap_mb,
            timeout_seconds=args.timeout,
            preferred_decompiler=args.decompiler,
        )
        return 0 if result and result.get("failed", 0) == 0 else 1

    out_dir = Path(args.output_dir or (PROJECT_ROOT / "VRProject" / "ERP" / "decompilados"))
    result = decompile_jars(
        jar_paths=args.jars,
        output_dir=out_dir,
        project_root=PROJECT_ROOT / "VRProject",
        max_workers=args.workers,
        max_cpu_cores=global_cfg["max_cpu_cores"],
        heap_mb=args.heap_mb,
        timeout_seconds=args.timeout,
        preferred_decompiler=args.decompiler,
    )
    return 0 if result.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
