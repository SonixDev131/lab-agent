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
UPDATE_SERVER_URL = (
    "http://localhost/api/agent/update"  # Replace with your update server URL
)
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


def extract_files(install_dir):
    """
    Extract all necessary files to the installation directory.

    This function:
    1. Creates the destination directory structure
    2. Copies the updater components to the installation directory
    3. Copies the main application files
    4. Sets up the configuration
    """
    logger.info(f"Installing to: {install_dir}")

    try:
        # Create installation directory structure
        os.makedirs(install_dir, exist_ok=True)
        os.makedirs(os.path.join(install_dir, "update_system"), exist_ok=True)
        os.makedirs(os.path.join(install_dir, "lab_agent_core"), exist_ok=True)
        os.makedirs(os.path.join(install_dir, "config"), exist_ok=True)
        logger.debug(f"Created installation directory structure in: {install_dir}")

        # Get the path to the embedded files
        # Running from a PyInstaller bundle (_MEIPASS will be set)
        bundle_dir = getattr(
            sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__))
        )
        logger.debug(f"Bundle directory: {bundle_dir}")

        # List files in the bundle directory for debugging
        try:
            logger.debug(f"Files in bundle directory: {os.listdir(bundle_dir)}")
        except Exception as e:
            logger.error(f"Failed to list files in bundle directory: {e}")

        # Copy update system files
        updater_files = ["updater.py", "update_server.py", "extractor.py"]
        for file in updater_files:
            src = os.path.join(bundle_dir, file)
            dst = os.path.join(install_dir, "update_system", file)
            if os.path.exists(src):
                logger.debug(f"Copying {src} to {dst}")
                shutil.copy2(src, dst)
                logger.debug(f"File copied successfully: {file}")
            else:
                logger.warning(f"Could not find file: {src}")

        # Create __init__.py in the update_system directory
        with open(os.path.join(install_dir, "update_system", "__init__.py"), "w") as f:
            f.write("# Update system package\n")

        # Copy lab_agent_core files
        core_files = [
            "main.py",
            "metrics_collector.py",
            "command_listener.py",
            "registration.py",
        ]
        for file in core_files:
            src = os.path.join(bundle_dir, file)
            dst = os.path.join(install_dir, "lab_agent_core", file)
            if os.path.exists(src):
                logger.debug(f"Copying {src} to {dst}")
                shutil.copy2(src, dst)
                logger.debug(f"File copied successfully: {file}")
            else:
                logger.warning(f"Could not find file: {src}")

        # Create __init__.py in the lab_agent_core directory
        with open(os.path.join(install_dir, "lab_agent_core", "__init__.py"), "w") as f:
            f.write("# Lab Agent Core package\n")

        # Copy config files
        config_files = ["agent_config.json", "config_loader.py"]
        for file in config_files:
            src = os.path.join(bundle_dir, file)
            dst = os.path.join(install_dir, "config", file)
            if os.path.exists(src):
                logger.debug(f"Copying {src} to {dst}")
                shutil.copy2(src, dst)
                logger.debug(f"File copied successfully: {file}")
            else:
                logger.warning(f"Could not find file: {src}")

        # Create __init__.py in the config directory
        with open(os.path.join(install_dir, "config", "__init__.py"), "w") as f:
            f.write("# Configuration package\n")

        # Create a basic runner script at the root level
        runner_path = os.path.join(install_dir, "run.py")
        with open(runner_path, "w") as f:
            f.write(
                """import os
import sys
import subprocess

# Add the installation directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import and run the main module
from lab_agent_core.main import main

if __name__ == "__main__":
    main()
"""
            )
        logger.debug(f"Created runner script at: {runner_path}")

        # Copy log file to installation directory for reference
        if os.path.exists(log_file):
            log_dst = os.path.join(install_dir, "installer.log")
            logger.debug(f"Copying log file to installation directory: {log_dst}")
            shutil.copy2(log_file, log_dst)

    except Exception as e:
        logger.error(f"Error during extraction process: {e}", exc_info=True)


def start_application(install_dir):
    """
    Start the main application after installation.
    This directly starts the main application instead of going through the updater.
    """
    runner_path = os.path.join(install_dir, "run.py")

    if os.path.exists(runner_path):
        logger.info("Starting Lab Agent application...")
        try:
            # Create arguments
            args = [sys.executable, runner_path]
            logger.debug(f"Running application with command: {' '.join(args)}")

            # Start the process
            process = subprocess.Popen(
                args,
                cwd=install_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            logger.debug(f"Application process started with PID: {process.pid}")

            return True
        except Exception as e:
            logger.error(f"Failed to start application: {e}", exc_info=True)
            return False
    else:
        logger.error(f"Error: Runner script not found at {runner_path}")
        # List directory contents for debugging
        try:
            logger.debug(f"Files in installation directory: {os.listdir(install_dir)}")
        except Exception as e:
            logger.error(f"Failed to list installation directory: {e}")
        return False


def main():
    """
    Main installer function that orchestrates the installation process.

    The installer follows a logical sequence:
    1. Check system requirements and dependencies
    2. Determine appropriate installation location
    3. Extract and configure application components
    4. Launch the application for immediate use
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

        # Extract all files
        extract_files(install_dir)

        # Update agent_config.json with version and update server information
        config_path = os.path.join(install_dir, "config", "agent_config.json")
        if os.path.exists(config_path):
            try:
                import json

                with open(config_path, "r") as f:
                    config = json.load(f)

                # Update config with version and server URL
                config["app_version"] = VERSION
                config["update_server_url"] = UPDATE_SERVER_URL

                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2)

                logger.debug(
                    f"Updated configuration with version {VERSION} and server URL"
                )
            except Exception as e:
                logger.error(f"Failed to update configuration: {e}")

        # Log installation time
        elapsed = time.time() - start_time
        logger.info(f"Installation completed in {elapsed:.2f} seconds")

        # Start the main application directly
        app_started = start_application(install_dir)

        if app_started:
            logger.info(f"\n{APP_NAME} has been successfully installed and started!")
        else:
            logger.warning(
                f"\n{APP_NAME} has been installed but could not be started automatically."
            )
            logger.info(
                f"You can start it manually from: {os.path.join(install_dir, 'run.py')}"
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
