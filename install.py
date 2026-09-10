#!/usr/bin/env python3
"""Instalador cross-platform del Trading Agent."""
import subprocess
import sys


COMANDOS = """
Comandos disponibles:
  GUI de escritorio:   python gui_charts.py
  Servidor + web UI:   uvicorn server.app:app --host 0.0.0.0 --port 8000
  Bot headless:        python -m backend.main
  Backtesting (CLI):   python -m backend.backtesting runtime --help
  Tests:               python -m pytest tests -q
"""


def main():
    if sys.version_info < (3, 9):
        print(
            f"ERROR: Python 3.9+ requerido. "
            f"Tienes {sys.version_info.major}.{sys.version_info.minor}."
        )
        sys.exit(1)
    print(f"Python {sys.version_info.major}.{sys.version_info.minor} — OK")

    print("\nInstalando dependencias...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        check=False,
    )
    if r.returncode != 0:
        print("\nERROR: pip install falló. Revisa el output anterior.")
        sys.exit(r.returncode)
    print("Dependencias instaladas correctamente.")

    if sys.platform == "win32":
        print("\n[Windows] MetaTrader5 disponible: puedes usar TRADING_BROKER=mt5.")
        print("Abre MT5 y deja la cuenta conectada antes de operar en vivo.")
    else:
        name = "macOS" if sys.platform == "darwin" else "Linux"
        print(f"\n[{name}] MetaTrader5 no está disponible en esta plataforma.")
        print("El sistema funciona igualmente con el broker de papel:")
        print("  export TRADING_BROKER=paper")
        print("Los datos históricos para backtesting vienen de Dukascopy, que no")
        print("requiere MT5.")
        if sys.platform == "linux":
            print("\n[Linux] La GUI de escritorio requiere libwebkit2gtk del sistema:")
            print("  Ubuntu/Debian:  sudo apt install libwebkit2gtk-4.0-dev")
            print("  Fedora:         sudo dnf install webkitgtk4")
            print("  Arch:           sudo pacman -S webkit2gtk")
            print("Si solo vas a usar el servidor y la web UI, no hace falta.")

    print(COMANDOS)
    print("Instalación completada.")


if __name__ == "__main__":
    main()
