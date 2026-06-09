#!/usr/bin/env python3
"""Instalador cross-platform del Trading Bot."""
import subprocess
import sys


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

    plat = sys.platform
    if plat == "win32":
        print("\n[Windows] Instalación completa. Comandos disponibles:")
        print("  GUI:          python gui_charts.py")
        print("  Headless:     python main.py")
        print("  Backtesting:  python -m backtesting runtime --data-source mt5 ...")
        print("                python -m backtesting runtime --data-source dukascopy ...")
    else:
        name = "macOS" if plat == "darwin" else "Linux"
        print(f"\n[{name}] mt5linux instalado. Para trading en vivo necesitas:")
        print("  1. En tu Windows con MT5: pip install mt5linux")
        print("     Iniciar el servidor:   python -c \"from mt5linux import MetaTrader5Server; MetaTrader5Server().start()\"")
        print("  2. En config.py de este proyecto: configura MT5LINUX_HOST y MT5LINUX_PORT")
        print("\nComandos disponibles una vez configurado:")
        print("  GUI:          python gui_charts.py")
        print("  Headless:     python main.py")
        print("  Backtesting:  python -m backtesting runtime --data-source dukascopy \\")
        print("                  --symbol EURUSD --start 2024-01-01 --end 2024-12-31 \\")
        print("                  --strategy-key nombre_estrategia")
        if plat == "linux":
            print("\n[Linux] La GUI requiere libwebkit2gtk-4.0 del sistema:")
            print("  Ubuntu/Debian:  sudo apt install libwebkit2gtk-4.0-dev")
            print("  Fedora:         sudo dnf install webkitgtk4")
            print("  Arch:           sudo pacman -S webkit2gtk")

    print("\nInstalación completada.")


if __name__ == "__main__":
    main()
