import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime

# Application constants
APP_NAME = "Lab Agent"
UPDATE_SERVER_URL = "http://localhost/api/agent/update"  # Replace as needed
VERSION = "1.0.0"
SERVICE_NAME = "LabAgentService"
NSSM_URL = "https://nssm.cc/release/nssm-2.24.zip"
NSSM_ZIP = "nssm.zip"
NSSM_EXE = "nssm.exe"


# Configure logging
def configure_logging():
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"installer_{timestamp}.log")
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=log_format,
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )
    return log_file


log_file = configure_logging()
logger = logging.getLogger("Installer")


def get_appdata_path():
    path = os.path.join(os.environ["LOCALAPPDATA"], APP_NAME)
    logger.debug(f"AppData path: {path}")
    return path


def extract_files(install_dir):
    logger.info(f"Installing to: {install_dir}")
    try:
        os.makedirs(install_dir, exist_ok=True)
        bundle_dir = getattr(
            sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__))
        )
        logger.debug(f"Bundle directory: {bundle_dir}")
        # Copy main.py
        main_src = os.path.join(bundle_dir, "main.py")
        main_dst = os.path.join(install_dir, "main.py")
        if os.path.exists(main_src):
            shutil.copy2(main_src, main_dst)
            logger.debug(f"Copied main.py to {main_dst}")
        else:
            logger.error(f"main.py not found in bundle directory: {main_src}")
        # Optionally copy agent_config.json if present
        config_src = os.path.join(bundle_dir, "agent_config.json")
        config_dst = os.path.join(install_dir, "agent_config.json")
        if os.path.exists(config_src):
            shutil.copy2(config_src, config_dst)
            logger.debug(f"Copied agent_config.json to {config_dst}")
        # Copy log file to installation directory for reference
        if os.path.exists(log_file):
            log_dst = os.path.join(install_dir, "installer.log")
            shutil.copy2(log_file, log_dst)
    except Exception as e:
        logger.error(f"Error during extraction process: {e}", exc_info=True)


def update_config(install_dir):
    config_path = os.path.join(install_dir, "agent_config.json")
    if os.path.exists(config_path):
        try:
            import json

            with open(config_path, "r") as f:
                config = json.load(f)
            config["app_version"] = VERSION
            config["update_server_url"] = UPDATE_SERVER_URL
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            logger.debug(f"Updated configuration with version {VERSION} and server URL")
        except Exception as e:
            logger.error(f"Failed to update configuration: {e}")


def download_and_extract_nssm(install_dir):
    nssm_dir = os.path.join(install_dir, "nssm")
    nssm_exe_path = os.path.join(nssm_dir, NSSM_EXE)
    if os.path.exists(nssm_exe_path):
        logger.info(f"NSSM already exists at {nssm_exe_path}")
        return nssm_exe_path
    try:
        os.makedirs(nssm_dir, exist_ok=True)
        zip_path = os.path.join(nssm_dir, NSSM_ZIP)
        logger.info(f"Downloading NSSM from {NSSM_URL}...")
        urllib.request.urlretrieve(NSSM_URL, zip_path)
        logger.info("Extracting NSSM...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # NSSM zip contains win32 and win64 folders; pick win64 if on 64-bit
            arch_folder = "win64" if sys.maxsize > 2**32 else "win32"
            for member in zip_ref.namelist():
                if member.endswith(f"{arch_folder}/nssm.exe"):
                    zip_ref.extract(member, nssm_dir)
                    src = os.path.join(nssm_dir, member)
                    shutil.move(src, nssm_exe_path)
                    break
        os.remove(zip_path)
        logger.info(f"NSSM extracted to {nssm_exe_path}")
        return nssm_exe_path
    except Exception as e:
        logger.error(f"Failed to download or extract NSSM: {e}")
        return None


def add_to_path(nssm_dir):
    current_path = os.environ.get("PATH", "")
    if nssm_dir not in current_path:
        os.environ["PATH"] = nssm_dir + os.pathsep + current_path
        logger.info(f"Added NSSM directory to PATH: {nssm_dir}")


def install_service_with_nssm(install_dir, nssm_exe_path):
    try:
        main_py_path = os.path.join(install_dir, "main.py")
        # Remove service if it already exists
        subprocess.run([nssm_exe_path, "remove", SERVICE_NAME, "confirm"], check=False)
        # Install service
        args = [nssm_exe_path, "install", SERVICE_NAME, main_py_path]
        logger.info(f"Installing service with NSSM: {' '.join(args)}")
        subprocess.run(args, check=True)
        # Set service to start automatically
        subprocess.run(
            [nssm_exe_path, "set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"],
            check=True,
        )
        # Redirect service logs
        log_path = os.path.join(install_dir, "service-error.log")
        subprocess.run(
            [nssm_exe_path, "set", SERVICE_NAME, "AppStderr", log_path], check=True
        )
        subprocess.run(
            [nssm_exe_path, "set", SERVICE_NAME, "AppStdout", log_path], check=True
        )
        # Start the service
        subprocess.run([nssm_exe_path, "start", SERVICE_NAME], check=True)
        logger.info(f"Service '{SERVICE_NAME}' installed and started successfully.")
    except Exception as e:
        logger.error(f"Failed to install/start service with NSSM: {e}")


def start_application(install_dir):
    main_py_path = os.path.join(install_dir, "main.py")
    if os.path.exists(main_py_path):
        logger.info("Starting Lab Agent application...")
        try:
            args = [sys.executable, main_py_path]
            logger.debug(f"Running application with command: {' '.join(args)}")
            process = subprocess.Popen(
                args,
                cwd=install_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE
                if sys.platform == "win32"
                else 0,
            )
            logger.debug(f"Application process started with PID: {process.pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to start application: {e}", exc_info=True)
            return False
    else:
        logger.error(f"main.py not found at {main_py_path}")
        return False


def main():
    logger.info(f"=== {APP_NAME} Installer ===")
    logger.info(f"Version: {VERSION}")
    logger.info(f"System platform: {sys.platform}")
    logger.info(f"System information: {sys.version}")
    try:
        install_dir = get_appdata_path()
        start_time = time.time()
        extract_files(install_dir)
        update_config(install_dir)
        # Download and setup NSSM, then install service
        nssm_exe_path = download_and_extract_nssm(install_dir)
        if nssm_exe_path:
            add_to_path(os.path.dirname(nssm_exe_path))
            install_service_with_nssm(install_dir, nssm_exe_path)
        else:
            logger.error("NSSM could not be set up. Service installation skipped.")
        elapsed = time.time() - start_time
        logger.info(f"Installation completed in {elapsed:.2f} seconds")
        app_started = start_application(install_dir)
        if app_started:
            logger.info(f"\n{APP_NAME} has been successfully installed and started!")
        else:
            logger.warning(
                f"\n{APP_NAME} has been installed but could not be started automatically."
            )
            logger.info(
                f"You can start it manually from: {os.path.join(install_dir, 'main.py')}"
            )
    except Exception as e:
        logger.critical(f"Installation failed with error: {e}", exc_info=True)
        print(f"\nInstallation failed. Please check the log file at: {log_file}")
        input("Press Enter to exit...")


if __name__ == "__main__":
    try:
        logger.info("Installer started")
        main()
        logger.info("Installer completed successfully")
        input("\nPress Enter to exit the installer...")
    except Exception as e:
        logger.critical(f"Unhandled exception in installer: {e}", exc_info=True)
        print(
            f"\nAn unexpected error occurred. Please check the log file at: {log_file}"
        )
        input("Press Enter to exit...")
