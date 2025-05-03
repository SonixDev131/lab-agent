import threading
import time
import sys
import os
import logging

# Add parent directory to path so we can import from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from lab_agent_core
from metrics_collector import MetricsCollector
from command_listener import CommandListener
from registration import register_computer

# Import configuration system
from config.config_loader import get_config, get_value

# Import update system components directly
from update_system.updater import Updater

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("agent.log")],
)
logger = logging.getLogger("LabAgent")


def check_for_updates():
    """
    Integrated update checker that checks directly for updates
    instead of using the auto_updater module.
    """
    try:
        # Get configuration values
        current_version = get_value("app_version", "1.0.0")
        framework_version = get_value("framework_version", "1.0")
        update_server_url = get_value("update_server_url", "https://yourdomain.com")
        
        logger.info(f"Checking for updates. Current version: {current_version}")
        
        # Initialize updater directly
        updater = Updater(current_version, update_server_url, framework_version)
        
        # Check if updates are available
        update_needed, latest_version, package_info = updater.check_for_updates()
        
        if update_needed:
            logger.info(f"Update available: {latest_version}")
            # Perform the update
            success = updater.perform_update()
            
            if success:
                logger.info("Update process initiated. Application will restart automatically.")
                return True
            else:
                logger.warning("Update process failed or was cancelled.")
                return False
        else:
            logger.info("No updates available. Starting application normally.")
            return False
            
    except Exception as e:
        logger.error(f"Error checking for updates: {e}", exc_info=True)
        return False


def main():
    logger.info("Starting Lab Agent...")

    # Load configuration
    config = get_config()
    logger.info(f"Current version: {config.get('app_version', '1.0.0')}")

    # Check for updates before starting the application
    logger.info("Checking for updates...")
    try:
        update_initiated = check_for_updates()
        if update_initiated:
            logger.info("Update process initiated. Application will exit and restart after update.")
            # The update process will restart the application when complete
            return
        logger.info("No new updates or update check failed. Continuing with application startup.")
    except Exception as e:
        logger.error(f"Error during update check: {e}")
        logger.info("Skipping update process and continuing with application startup.")

    # Check and register computer
    computer_id, room_id = register_computer()
    if not computer_id or not room_id:
        logger.error("Cannot register computer. Exiting...")
        exit(1)

    # Initialize modules
    logger.info(f"Initializing modules with computer_id={computer_id}, room_id={room_id}")
    metrics = MetricsCollector(computer_id, room_id)
    listener = CommandListener(computer_id, room_id)

    # Run threads
    metrics_thread = threading.Thread(target=metrics.start, name="MetricsThread")
    listener_thread = threading.Thread(
        target=listener.start, name="CommandListenerThread"
    )
    metrics_thread.daemon = True
    listener_thread.daemon = True

    metrics_thread.start()
    listener_thread.start()

    logger.info("All modules have been started.")

    # Main loop, keep the program running
    try:
        # Get update check interval from config (default to 12 hours if not set)
        update_check_interval = get_value("update_check_interval", 12 * 60 * 60)
        last_update_check = time.time()

        while True:
            current_time = time.time()

            # Check for updates periodically
            if current_time - last_update_check > update_check_interval:
                logger.info("Performing scheduled update check...")
                update_initiated = check_for_updates()
                if update_initiated:
                    logger.info("Update initiated, application will restart.")
                    break  # Exit the loop to allow the update process to take over
                last_update_check = current_time

            time.sleep(60)  # Check every minute

    except KeyboardInterrupt:
        logger.info("Received interrupt signal. Stopping agent...")
        metrics.stop()
        listener.stop()
        metrics_thread.join(timeout=3)
        listener_thread.join(timeout=3)
        logger.info("Agent stopped.")


if __name__ == "__main__":
    main()
