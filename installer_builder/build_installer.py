import os
import shutil
import subprocess
import sys


def build_installer():
    """
    Build the standalone installer executable using PyInstaller.
    This script compiles the installer.py into a single executable that contains
    the updater embedded within it.
    """
    print("Building standalone installer...")

    # Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "PyInstaller"])

    # Create a temporary directory for bundling the updater
    if os.path.exists("temp"):
        shutil.rmtree("temp")
    os.makedirs("temp", exist_ok=True)

    # Copy the updater files to be embedded in the installer
    print("Packaging updater for embedding...")
    updater_files = ["updater.py", "update_server.py", "extractor.py"]
    for file in updater_files:
        src = os.path.join("..", "update_system", file)
        dst = os.path.join("temp", file)
        if os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            print(f"Warning: Could not find updater file: {src}")
    # Create the spec file for PyInstaller
    spec_content = """
# -*- mode: python ; coding: utf-8 -*-

added_files = [
    ('temp/updater.py', '.'),
    ('temp/update_server.py', '.'),
    ('temp/extractor.py', '.')
]

a = Analysis(
    ['installer.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
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
