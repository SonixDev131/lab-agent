import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sys
import threading
import time
import zipfile
from typing import Any, Optional, Tuple

import psutil
import requests
import subprocess
import signal
import pika

# ===================== LOGGER =====================
logger = logging.getLogger("Agent")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("agent.log")],
)

# ===================== CONSTANTS =====================
AGENT_ZIP = "agent_new.zip"
UPDATE_TEMP = "update_temp"
CONFIG_FILE = "agent_config.json"
HASH_FILE = "file_hashes.json"
APP_URL = "http://host.docker.internal"
UPDATE_ENDPOINT = "/api/agent/update"
RABBITMQ_URL = "amqp://guest:guest@host.docker.internal:5672/"
SERVICE_NAME = "LabAgentService"  # or your actual service name
UPDATER_DIR = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.path.join(UPDATER_DIR, AGENT_ZIP)
EXTRACT_DIR = os.path.join(UPDATER_DIR, UPDATE_TEMP)
CONFIG_KEYS = {"mac_address", "hostname", "room_id", "computer_id"}


# ===================== CONFIG LOADER =====================
def get_config_info() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        # Chỉ lấy 4 trường cần thiết
        return {k: data.get(k) for k in CONFIG_KEYS}
    except Exception as e:
        logger.error(f"[get_config_info] Config read error: {e}")
        return {k: None for k in CONFIG_KEYS}


def set_value(key: str, value: str) -> None:
    try:
        data = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    pass
        data[key] = value
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
        logger.info(f"[set_value] Updated config: set {key} = {value}")
    except Exception as e:
        logger.error(f"[set_value] Failed to update config: {e}")


# ===================== REGISTRATION =====================
def get_mac_address() -> Optional[str]:
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for interface in addrs:
            if any(
                k in interface.lower()
                for k in ["loopback", "virtual", "vmnet", "veth", "docker"]
            ):
                continue
            if interface in stats and stats[interface].isup:
                for addr in addrs[interface]:
                    if addr.family == psutil.AF_LINK:
                        mac = addr.address
                        if re.match(r"^([0-9A-Fa-f]{2}-){5}([0-9A-Fa-f]{2})$", mac):
                            return mac
        return None
    except Exception as e:
        logger.error(f"[get_mac_address] MAC address error: {e}")
        return None


def register_computer() -> Tuple[Optional[str], Optional[str]]:
    config = get_config_info()
    computer_id = config["computer_id"]
    room_id = config["room_id"]
    if computer_id and room_id:
        logger.info(f"Already registered: computer_id={computer_id}, room_id={room_id}")
        return computer_id, room_id
    try:
        register_data = {
            "mac_address": get_mac_address(),
            "hostname": platform.node(),
        }
        logger.info(f"Registering computer: {register_data}")
        response = requests.post(f"{APP_URL}/agents/register", json=register_data)
        if response.status_code == 200:
            result = response.json()
            room_id = result.get("room_id")
            computer_id = result.get("computer_id")
            if room_id and computer_id:
                register_data["room_id"] = room_id
                register_data["computer_id"] = computer_id
                # Lưu lại 4 trường vào file config
                with open(CONFIG_FILE, "w") as f:
                    json.dump({k: register_data[k] for k in CONFIG_KEYS}, f, indent=4)
                logger.info(
                    f"Registration successful: computer_id={computer_id}, room_id={room_id}"
                )
                return computer_id, room_id
            else:
                logger.error(
                    "[register_computer] Registration failed: Missing room_id or computer_id"
                )
        else:
            logger.error(
                f"[register_computer] Registration failed: {response.status_code} - {response.text}"
            )
    except Exception as e:
        logger.error(f"[register_computer] Registration error: {e}")
    return None, None


# ===================== METRICS =====================
def get_system_metrics() -> dict:
    try:
        return {
            "cpu_usage": psutil.cpu_percent(interval=1),
            "memory_total": psutil.virtual_memory().total,
            "memory_used": psutil.virtual_memory().used,
            "disk_total": psutil.disk_usage("/").total,
            "disk_used": psutil.disk_usage("/").used,
            "uptime": int(time.time() - psutil.boot_time()),
            "platform": platform.system(),
            "platform_version": platform.version(),
            "hostname": platform.node(),
        }
    except Exception as e:
        logger.error(f"[get_system_metrics] Error collecting system metrics: {e}")
        return {"error": str(e)}


def send_status_update(
    computer_id: str, room_id: str, rabbitmq_url: str, status: str = "online"
) -> bool:
    try:
        logger.debug(f"Connecting to RabbitMQ at {rabbitmq_url}")
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        logger.debug("RabbitMQ connection established")
        
        channel = connection.channel()
        logger.debug("RabbitMQ channel created")
        
        channel.queue_declare(queue="metrics", durable=True)
        logger.debug("Queue 'metrics' declared")
        
        status_data = {
            "computer_id": computer_id,
            "room_id": room_id,
            "status": status,
            "timestamp": int(time.time()),
            "metrics": get_system_metrics(),
        }
        logger.debug(f"Preparing to send status data: {json.dumps(status_data, indent=2)}")
        
        channel.basic_publish(
            exchange="",
            routing_key="metrics",
            body=json.dumps(status_data),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json",
            ),
        )
        logger.debug("Message published successfully")
        
        connection.close()
        logger.debug("RabbitMQ connection closed")
        logger.info(f"Status update sent: {status}")
        return True
    except Exception as e:
        logger.error(f"[send_status_update] Error sending status update: {e}", exc_info=True)
        return False


def metrics_heartbeat(
    computer_id: str, room_id: str, rabbitmq_url: str, interval: int, running_flag: list
) -> None:
    logger.debug(f"Starting metrics heartbeat with interval: {interval} seconds")
    send_status_update(computer_id, room_id, rabbitmq_url, "online")
    while running_flag[0]:
        time.sleep(interval)
        if running_flag[0]:
            logger.debug("Sending periodic status update")
            send_status_update(computer_id, room_id, rabbitmq_url, "online")


def start_metrics_thread(
    computer_id: str, room_id: str, rabbitmq_url: str, interval: int, running_flag: list
) -> threading.Thread:
    thread = threading.Thread(
        target=metrics_heartbeat,
        args=(computer_id, room_id, rabbitmq_url, interval, running_flag),
        daemon=True,
    )
    thread.start()
    return thread


# ===================== COMMAND LISTENER =====================
def process_command(command_data: dict) -> bool:
    try:
        command_type = command_data.get("command", "")
        logger.info(f"Processing command: {command_type}")

        if command_type == "UPDATE":
            logger.info("Received update command. Initiating update process in a new thread...")
            threading.Thread(target=check_for_updates, daemon=True).start()
            return True

        # Implement other command handling here

        return True
    except Exception as e:
        logger.error(f"[process_command] Error processing command: {e}")
        return False


def command_callback(
    ch, method, properties, body, computer_id: str, room_id: str
) -> None:
    try:
        message = json.loads(body.decode("utf-8"))
        source = "default"
        if method.exchange == "cmd.direct":
            source = f"CMD (room.{room_id})"
        elif method.exchange == "broadcast.fanout":
            source = "BROADCAST"
        elif method.exchange == "":
            source = "DIRECT (MAC)"
        logger.info(f"Received message from {source}: {json.dumps(message, indent=2)}")
        if "command" in message:
            process_command(message)
    except json.JSONDecodeError:
        logger.error(f"[command_callback] Cannot decode JSON: {body.decode('utf-8')}")
    except Exception as e:
        logger.error(f"[command_callback] Error handling message: {e}")
    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_command_listener(
    computer_id: str, room_id: str, rabbitmq_url: str, running_flag: list
) -> None:
    import pika

    try:
        logger.debug(f"Starting command listener with RabbitMQ URL: {rabbitmq_url}")
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            mac_address = data["mac_address"]
        queue_name = mac_address
        logger.debug(f"Using queue name: {queue_name}")
        
        logger.debug("Establishing RabbitMQ connection for command listener")
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()
        logger.debug("RabbitMQ channel created for command listener")
        
        channel.queue_declare(queue=queue_name, durable=True)
        logger.debug(f"Queue declared: {queue_name}")
        
        channel.exchange_declare(
            exchange="cmd.direct", exchange_type="direct", durable=True
        )
        logger.debug("Direct exchange declared: cmd.direct")
        
        channel.queue_bind(
            exchange="cmd.direct",
            queue=queue_name,
            routing_key=f"room.{room_id}",
        )
        logger.debug(f"Queue bound to direct exchange with routing key: room.{room_id}")
        
        channel.exchange_declare(
            exchange="broadcast.fanout", exchange_type="fanout", durable=True
        )
        logger.debug("Fanout exchange declared: broadcast.fanout")
        
        channel.queue_bind(exchange="broadcast.fanout", queue=queue_name)
        logger.debug(f"Queue bound to fanout exchange")
        
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=lambda ch, method, properties, body: command_callback(
                ch, method, properties, body, computer_id, room_id
            ),
            auto_ack=False,
        )
        logger.debug(f"Basic consume set up for queue: {queue_name}")
        
        logger.info(
            f"Listening for commands for MAC={mac_address}, room={room_id}, computer_id={computer_id}"
        )
        while running_flag[0]:
            connection.process_data_events(time_limit=1.0)
            
        logger.debug("Command listener loop ended, closing connection")
        connection.close()
    except Exception as e:
        logger.error(f"[start_command_listener] Error in command listener: {e}", exc_info=True)


# ===================== FILE HELPERS =====================
def safe_remove(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.info(f"Removed file: {path}")
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            logger.info(f"Removed directory: {path}")
    except Exception as e:
        logger.warning(f"[safe_remove] Failed to remove {path}: {e}")

# ===================== EXTRACTOR LOGIC =====================
def extract_update() -> str:
    try:
        if not os.path.exists(EXTRACT_DIR):
            os.makedirs(EXTRACT_DIR, exist_ok=True)
        with zipfile.ZipFile(ZIP_PATH, "r") as zip_ref:
            zip_ref.extractall(EXTRACT_DIR)
        logger.info(f"Update package extracted to: {EXTRACT_DIR}")
        return EXTRACT_DIR
    except Exception as e:
        logger.error(f"[extract_update] Error extracting update package: {e}")
        raise

# ===================== UPDATER =====================

def get_file_hash(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def create_file_hash_table() -> dict:
    logger.info("Creating hash table for main.py and requirements.txt...")
    original_dir = os.getcwd()
    try:
        os.chdir(UPDATER_DIR)
        file_hashes = {}
        target_files = ["main.py", "requirements.txt"]
        for file in target_files:
            file_path = file
            if os.path.isfile(file_path):
                try:
                    file_hash = get_file_hash(file_path)
                    file_hashes[file] = file_hash
                except Exception as e:
                    logger.error(
                        f"[create_file_hash_table] Error hashing file {file_path}: {e}"
                    )
        hash_file_path = os.path.join(UPDATER_DIR, HASH_FILE)
        with open(hash_file_path, "w") as f:
            json.dump(file_hashes, f, indent=2)
        logger.info(
            f"Created hashes for {len(file_hashes)} files and saved to {hash_file_path}"
        )
        return file_hashes
    finally:
        os.chdir(original_dir)

def send_hash_table_to_server(
    file_hashes: dict
) -> Optional[str]:
    try:
        response = requests.post(
            f"{APP_URL}{UPDATE_ENDPOINT}",
            json={"hash_table": file_hashes},
            stream=True,
        )
        if response.status_code == 200:
            with open(ZIP_PATH, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logger.info(f"Delta package zip file saved to {ZIP_PATH}")
            return ZIP_PATH
        else:
            logger.error(
                f"[send_hash_table_to_server] Failed to download delta package: {response.status_code} - {response.text}"
            )
            return None
    except Exception as e:
        logger.error(
            f"[send_hash_table_to_server] Error downloading delta package: {e}"
        )
        return None
    
def install_update() -> bool:
    try:
        for root, dirs, files in os.walk(EXTRACT_DIR):
            for file in files:
                src = os.path.join(root, file)
                rel_path = os.path.relpath(src, EXTRACT_DIR)
                dst = os.path.join(os.getcwd(), rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(src, dst)
                logger.info(f"Installed: {rel_path}")
        logger.info("Update installation completed")
        return True
    except Exception as e:
        logger.error(f"[install_update] Error installing update: {e}")
        raise

def clean_up() -> bool:
    try:
        safe_remove(AGENT_ZIP)
        safe_remove(EXTRACT_DIR)
        logger.info("Temporary files cleaned up")
        return True
    except Exception as e:
        logger.error(f"[clean_up] Error during cleanup: {e}")
        return False

def restart_nssm_service(service_name=SERVICE_NAME):
    try:
        subprocess.run(["nssm", "stop", service_name], check=True)
        subprocess.run(["nssm", "start", service_name], check=True)
        logger.info(f"Service '{service_name}' restarted successfully.")
    except Exception as e:
        logger.error(f"Failed to restart service '{service_name}': {e}")

def check_for_updates() -> bool:
    try:
        # Create hash table and send to server
        file_hashes = create_file_hash_table()
        zip_file = send_hash_table_to_server(file_hashes)
        if not zip_file:
            logger.info("No delta package received from Update Server.")
            return False

        # Extract and install update
        extract_update()
        logger.info(f"Update extracted to {EXTRACT_DIR}.")
        install_update()

        # Cleanup and restart
        clean_up()
        restart_nssm_service()
        logger.info("Update process completed.")
        return True

    except Exception as e:
        logger.error(f"[check_for_updates] Update process failed: {e}")
        return False



# ===================== MAIN LOGIC =====================
def handle_shutdown_signal(signum=None, frame=None):
    logger.info("Received shutdown signal, sending offline status...")
    computer_id = get_config_info().get("computer_id")
    room_id = get_config_info().get("room_id")
    send_status_update(computer_id, room_id, RABBITMQ_URL, status="offline")
    sys.exit(0)


def main() -> None:
    logger.info("Starting Lab Agent...")

    logger.info("Checking for updates...")
    check_for_updates()

    computer_id, room_id = register_computer()
    if not computer_id or not room_id:
        logger.error("Cannot register computer. Exiting...")
        sys.exit(1)
    logger.info(
        f"Initializing modules with computer_id={computer_id}, room_id={room_id}"
    )
    metrics_running = [True]
    command_running = [True]
    start_metrics_thread(computer_id, room_id, RABBITMQ_URL, 30, metrics_running)
    command_thread = threading.Thread(
        target=start_command_listener,
        args=(computer_id, room_id, RABBITMQ_URL, command_running),
        daemon=True,
    )
    command_thread.start()
    logger.info("All modules have been started.")
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down agent...")
        metrics_running[0] = False
        command_running[0] = False
        # Send offline status before exiting
        send_status_update(computer_id, room_id, RABBITMQ_URL, status="offline")


if __name__ == "__main__":
    main()
