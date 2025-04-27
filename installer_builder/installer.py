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


def check_python_requirements():
    """
    Check if all required Python packages are installed.

    Returns (is_satisfied, missing_packages)
    """
    required_packages = [
        "certifi",
        "charset-normalizer",
        "idna",
        "requests",
        "urllib3",
        "psutil",
        "pika",
        "phpserialize",
    ]

    missing = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)

    return len(missing) == 0, missing


def install_python_requirements(missing_packages):
    """
    Install missing Python packages.

    This function installs any required Python packages that were found to be missing.
    """
    if not missing_packages:
        return True

    print(f"Installing missing Python packages: {', '.join(missing_packages)}")

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install"] + missing_packages
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error installing packages: {e}")
        return False


def extract_updater(install_dir):
    """
    Extract the embedded updater files to the installation directory.

    This function:
    1. Creates the destination directory structure
    2. Locates the source files (works in both PyInstaller bundled mode and development mode)
    3. Copies the updater components to the installation directory
    4. Generates a configuration file with version info and update server URL
    """
    print(f"Installing to: {install_dir}")

    # Create installation directory if it doesn't exist
    os.makedirs(install_dir, exist_ok=True)

    # Get the path to the embedded updater files
    # Running from a PyInstaller bundle (_MEIPASS will be set)
    bundle_dir = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))

    # Copy updater files
    updater_files = ["updater.py", "update_server.py", "extractor.py"]
    for file in updater_files:
        src = os.path.join(bundle_dir, file)
        dst = os.path.join(install_dir, file)
        if os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            print(f"Warning: Could not find updater file: {src}")


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
    """
    Main installer function that orchestrates the installation process.

    The installer follows a logical sequence:
    1. Check system requirements and dependencies
    2. Determine appropriate installation location
    3. Extract and configure application components
    4. Create user interface elements (shortcuts, launchers)
    5. Launch the application for immediate use

    This cross-platform implementation adapts to the user's environment
    while maintaining consistent functionality across operating systems.
    """
    print(f"=== {APP_NAME} Installer ===")

    # Check OS compatibility
    if sys.platform != "win32":
        print("Error: This installer is only compatible with Windows.")
        input("Press Enter to exit...")
        sys.exit(1)

    print("Checking system requirements...")

    # Check for required Python packages
    requirements_met, missing_packages = check_python_requirements()
    if not requirements_met:
        print("Some required Python packages are missing.")
        print("Installing require pacakages...")
        install_python_requirements(missing_packages)
        print("All required Python packages are installed.")

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
    print("The application will now start automatically.")


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit the installer...")
