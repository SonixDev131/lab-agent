import os
import sys
import shutil
import subprocess
import tempfile
import winreg
import zipfile
import urllib.request
import ctypes
from pathlib import Path
import json

# Application constants
APP_NAME = "Lab Agent"
APP_PUBLISHER = "YourCompany"  # Replace with your company name
UPDATE_SERVER_URL = "https://yourdomain.com"  # Replace with your update server URL
VERSION = "1.0.0"


def is_admin():
    """Check if the current user has admin privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


def get_appdata_path():
    """Get the AppData\Local path for installing the application."""
    return os.path.join(os.environ["LOCALAPPDATA"], APP_NAME)


def check_dotnet_framework():
    """
    Check if the required .NET Framework is installed.
    Returns (is_installed, version)
    """
    try:
        # Check for .NET Framework 2.0/3.0
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v2.0.50727",
        ) as key:
            install = winreg.QueryValueEx(key, "Install")[0]
            if install == 1:
                version = winreg.QueryValueEx(key, "Version")[0]
                return True, version
        return False, None
    except:
        return False, None


def download_dotnet_framework():
    """
    Download and install the required .NET Framework.
    """
    print("Downloading .NET Framework 2.0...")
    dotnet_url = "https://download.microsoft.com/download/5/6/7/567758a3-759e-473e-bf8f-52154438565a/dotnetfx.exe"
    temp_file = os.path.join(tempfile.gettempdir(), "dotnetfx.exe")

    # Download the installer
    urllib.request.urlretrieve(dotnet_url, temp_file)

    # Run the installer silently
    print("Installing .NET Framework 2.0...")
    subprocess.call([temp_file, "/q", "/norestart"])

    # Clean up
    os.remove(temp_file)


def extract_updater(install_dir):
    """
    Extract the embedded Updater files to the installation directory.
    """
    print(f"Installing to: {install_dir}")

    # Create installation directory if it doesn't exist
    os.makedirs(install_dir, exist_ok=True)

    # Get the path to the embedded updater files
    bundle_dir = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))

    # Copy updater files
    updater_files = ["updater.py", "update_server.py", "extractor.py"]
    for file in updater_files:
        src = os.path.join(bundle_dir, file)
        dst = os.path.join(install_dir, file)
        if os.path.exists(src):
            shutil.copy2(src, dst)

    # Create a basic configuration file
    config = {"version": VERSION, "update_server_url": UPDATE_SERVER_URL}

    with open(os.path.join(install_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    print("Updater extracted successfully.")


def create_shortcut(install_dir):
    """
    Create shortcuts to the Updater in Start Menu and Desktop.
    """
    try:
        import win32com.client

        # Paths for shortcuts
        start_menu_path = os.path.join(
            os.environ["APPDATA"],
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            APP_PUBLISHER,
        )
        desktop_path = os.path.join(os.environ["USERPROFILE"], "Desktop")

        # Create Start Menu folder if it doesn't exist
        os.makedirs(start_menu_path, exist_ok=True)

        # Path to the updater launcher script
        updater_launcher = os.path.join(install_dir, "updater_launcher.bat")

        # Create a batch file to launch the updater
        with open(updater_launcher, "w") as f:
            f.write("@echo off\n")
            f.write(f'cd /d "{install_dir}"\n')
            f.write("python updater.py\n")

        # Create shortcuts
        shell = win32com.client.Dispatch("WScript.Shell")

        # Start Menu shortcut
        shortcut = shell.CreateShortCut(
            os.path.join(start_menu_path, f"{APP_NAME}.lnk")
        )
        shortcut.TargetPath = updater_launcher
        shortcut.WorkingDirectory = install_dir
        shortcut.Description = f"Launch {APP_NAME}"
        shortcut.Save()

        # Desktop shortcut
        shortcut = shell.CreateShortCut(os.path.join(desktop_path, f"{APP_NAME}.lnk"))
        shortcut.TargetPath = updater_launcher
        shortcut.WorkingDirectory = install_dir
        shortcut.Description = f"Launch {APP_NAME}"
        shortcut.Save()

        print("Shortcuts created successfully.")
    except ImportError:
        print("Warning: pywin32 not installed. Shortcuts not created.")
    except Exception as e:
        print(f"Error creating shortcuts: {e}")


def start_updater(install_dir):
    """
    Start the updater after installation.
    """
    updater_path = os.path.join(install_dir, "updater.py")

    if os.path.exists(updater_path):
        print("Starting Updater...")
        subprocess.Popen(
            [sys.executable, updater_path],
            cwd=install_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        print(f"Error: Updater not found at {updater_path}")


def main():
    """Main installer function."""
    print(f"=== {APP_NAME} Installer ===")

    # Check OS compatibility
    if sys.platform != "win32":
        print("Error: This installer is only compatible with Windows.")
        input("Press Enter to exit...")
        sys.exit(1)

    print("Checking system requirements...")

    # Check for .NET Framework
    dotnet_installed, dotnet_version = check_dotnet_framework()
    if not dotnet_installed:
        print(".NET Framework 2.0/3.0 is required but not installed.")
        if (
            input("Do you want to download and install it now? (Y/N): ").strip().upper()
            == "Y"
        ):
            download_dotnet_framework()
        else:
            print("Installation cannot continue without .NET Framework 2.0/3.0.")
            input("Press Enter to exit...")
            sys.exit(1)
    else:
        print(f".NET Framework version {dotnet_version} is installed.")

    # Get installation directory
    install_dir = get_appdata_path()

    # Extract updater
    extract_updater(install_dir)

    # Create shortcuts
    try:
        create_shortcut(install_dir)
    except Exception as e:
        print(f"Warning: Could not create shortcuts: {e}")

    # Start the updater
    start_updater(install_dir)

    print(f"\n{APP_NAME} has been successfully installed!")
    print(f"The application will now start automatically.")


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit the installer...")
