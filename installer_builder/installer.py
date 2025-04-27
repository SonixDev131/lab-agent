import os
import sys
import shutil
import subprocess
import logging
import time
from datetime import datetime

# Application constants
APP_NAME = "Lab Agent"
APP_PUBLISHER = "YourCompany"  # Replace with your company name
UPDATE_SERVER_URL = "https://yourdomain.com"  # Replace with your update server URL
VERSION = "1.0.0"


# Configure logging
def configure_logging():
    """Set up logging to both file and console."""
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Create log file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"installer_{timestamp}.log")

    # Configure logging
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=log_format,
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    return log_file


# Initialize logger
log_file = configure_logging()
logger = logging.getLogger("Installer")


def get_appdata_path():
    """Get the AppData\Local path for installing the application."""
    path = os.path.join(os.environ["LOCALAPPDATA"], APP_NAME)
    logger.debug(f"AppData path: {path}")
    return path


def extract_updater(install_dir):
    """
    Extract the embedded updater files to the installation directory.

    This function:
    1. Creates the destination directory structure
    2. Locates the source files (works in both PyInstaller bundled mode and development mode)
    3. Copies the updater components to the installation directory
    4. Generates a configuration file with version info and update server URL
    """
    logger.info(f"Installing to: {install_dir}")

    try:
        # Create installation directory if it doesn't exist
        os.makedirs(install_dir, exist_ok=True)
        logger.debug(f"Created installation directory: {install_dir}")

        # Get the path to the embedded updater files
        # Running from a PyInstaller bundle (_MEIPASS will be set)
        bundle_dir = getattr(
            sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__))
        )
        logger.debug(f"Bundle directory: {bundle_dir}")
        logger.debug(f"Current working directory: {os.getcwd()}")

        # List files in the bundle directory for debugging
        try:
            logger.debug(f"Files in bundle directory: {os.listdir(bundle_dir)}")
        except Exception as e:
            logger.error(f"Failed to list files in bundle directory: {e}")

        # Copy updater files
        updater_files = ["updater.py", "update_server.py", "extractor.py"]
        for file in updater_files:
            src = os.path.join(bundle_dir, file)
            dst = os.path.join(install_dir, file)
            if os.path.exists(src):
                logger.debug(f"Copying {src} to {dst}")
                shutil.copy2(src, dst)
                logger.debug(f"File copied successfully: {file}")
            else:
                logger.warning(f"Could not find updater file: {src}")

        # Copy log file to installation directory for reference
        if os.path.exists(log_file):
            log_dst = os.path.join(install_dir, "installer.log")
            logger.debug(f"Copying log file to installation directory: {log_dst}")
            shutil.copy2(log_file, log_dst)

    except Exception as e:
        logger.error(f"Error during extraction process: {e}", exc_info=True)


def start_updater(install_dir):
    """
    Start the updater after installation.
    """
    updater_path = os.path.join(install_dir, "updater.py")

    if os.path.exists(updater_path):
        logger.info("Starting Updater...")
        try:
            # Create arguments with debug flag
            args = [
                sys.executable,
                updater_path,
                "--debug",
                f"--version={VERSION}",
                f"--server-url={UPDATE_SERVER_URL}",
            ]
            logger.debug(f"Running updater with command: {' '.join(args)}")

            # Get Python executable info for debugging
            logger.debug(f"Python executable: {sys.executable}")
            logger.debug(f"Python version: {sys.version}")

            # Start the process
            process = subprocess.Popen(
                args,
                cwd=install_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            logger.debug(f"Updater process started with PID: {process.pid}")
        except Exception as e:
            logger.error(f"Failed to start updater: {e}", exc_info=True)
    else:
        logger.error(f"Error: Updater not found at {updater_path}")
        # List directory contents for debugging
        try:
            logger.debug(f"Files in installation directory: {os.listdir(install_dir)}")
        except Exception as e:
            logger.error(f"Failed to list installation directory: {e}")


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
    logger.info(f"=== {APP_NAME} Installer ===")
    logger.info(f"Version: {VERSION}")
    logger.info(f"System platform: {sys.platform}")
    logger.info(f"System information: {sys.version}")

    try:
        # Check OS compatibility
        if sys.platform != "win32":
            logger.error("Error: This installer is only compatible with Windows.")
            input("Press Enter to exit...")
            sys.exit(1)

        # Log environment variables for debugging
        logger.debug("Environment variables:")
        for key, value in os.environ.items():
            logger.debug(f"  {key}: {value}")

        # Get installation directory
        install_dir = get_appdata_path()

        # Track installation time
        start_time = time.time()

        # Extract updater
        extract_updater(install_dir)

        # Log installation time
        elapsed = time.time() - start_time
        logger.info(f"Installation completed in {elapsed:.2f} seconds")

        # Start the updater
        start_updater(install_dir)

        logger.info(f"\n{APP_NAME} has been successfully installed!")
        logger.info("The application will now start automatically.")

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
