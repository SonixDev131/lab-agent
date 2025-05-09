import os
import shutil
import subprocess
import sys


def build_installer():
    """
    Build the standalone installer executable using PyInstaller.
    This script compiles installer.py into a single executable and embeds main.py as a data file.
    """
    print("Building standalone installer...")

    # Ensure PyInstaller is installed
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "PyInstaller"])

    # Create a temporary directory for bundling
    temp_dir = "temp"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)

    # Copy main.py to temp for embedding
    print("Packaging main.py for embedding...")
    main_src = "main.py"
    main_dst = os.path.join(temp_dir, "main.py")
    if os.path.exists(main_src):
        shutil.copy2(main_src, main_dst)
    else:
        print(f"Warning: Could not find main.py at {main_src}")

    # Create the spec file for PyInstaller
    spec_content = f"""
# -*- mode: python ; coding: utf-8 -*-

added_files = [
    ('{temp_dir}/main.py', '.')
]

a = Analysis(
    ['installer.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={[]},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LabAgentInstaller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""

    with open("installer.spec", "w") as f:
        f.write(spec_content)

    # Run PyInstaller
    print("Running PyInstaller...")
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "installer.spec", "--clean"]
    )

    print("Installer built successfully! Find it in the 'dist' directory.")
    print("Executable: dist/LabAgentInstaller.exe")


if __name__ == "__main__":
    build_installer()
