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
        src = os.path.join("..", file)
        dst = os.path.join("temp", file)
        if os.path.exists(src):
            shutil.copy2(src, dst)

    # Create the spec file for PyInstaller
    spec_content = """
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Include the updater files as data
added_files = [
    ('temp/updater.py', '.'),
    ('temp/update_server.py', '.'),
    ('temp/extractor.py', '.')
]

a = Analysis(['installer.py'],
             pathex=[],
             binaries=[],
             datas=added_files,
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='LabAgentInstaller',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=True,
          icon='installer_icon.ico' if os.path.exists('installer_icon.ico') else None)
    """

    with open("installer.spec", "w") as f:
        f.write(spec_content)

    # Run PyInstaller
    print("Running PyInstaller...")
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "installer.spec", "--onefile", "--clean"]
    )

    print("Installer built successfully! Find it in the 'dist' directory.")
    print("Executable: dist/LabAgentInstaller.exe")


if __name__ == "__main__":
    build_installer()
