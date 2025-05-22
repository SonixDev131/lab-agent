import hashlib
import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import zipfile
from typing import Optional, Tuple

import pika
import psutil
import requests

# ===================== LOGGER =====================
logger = logging.getLogger("Agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("agent.log")],
)

# ===================== CONSTANTS =====================
AGENT_ZIP = "agent_new.zip"
UPDATE_TEMP = "update_temp"
CONFIG_FILE = "agent_config.json"
APP_URL = "http://host.docker.internal"
VERSION_FILE = "version.txt"
REGISTER_ENDPOINT = "/api/agents/register"
UPDATE_ENDPOINT = "/api/agent/update"
VERSION_ENDPOINT = "/api/agent/version"
COMMAND_RESULT_ENDPOINT = "/api/agent/command-result"
RABBITMQ_URL = "amqp://guest:guest@host.docker.internal:5672/"
SERVICE_NAME = "agent"  # or your actual service name
UPDATER_DIR = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.path.join(UPDATER_DIR, AGENT_ZIP)
EXTRACT_DIR = os.path.join(UPDATER_DIR, UPDATE_TEMP)
VERSION_FILE_PATH = os.path.join(UPDATER_DIR, VERSION_FILE)
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
        addrs = psutil.net_if_addrs()
        for interface in addrs:
            # Check if the interface has a valid MAC address
            if psutil.net_if_addrs()[interface][0].address:
                return psutil.net_if_addrs()[interface][0].address
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
        response = requests.post(f"{APP_URL}{REGISTER_ENDPOINT}", json=register_data)
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
            "firewall_status": get_firewall_status(),
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
        logger.debug(
            f"Preparing to send status data: {json.dumps(status_data, indent=2)}"
        )

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
        logger.error(
            f"[send_status_update] Error sending status update: {e}", exc_info=True
        )
        return False


def get_firewall_status() -> dict:
    try:
        cmd = "netsh advfirewall show allprofiles state"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        output = result.stdout
        status = {}
        for profile in ["Domain", "Private", "Public"]:
            match = re.search(
                rf"{profile} Profile Settings:[\s\S]*?State\s+(\w+)", output
            )
            if match:
                status[profile] = match.group(1)
        return status
    except Exception as e:
        return {"error": str(e)}


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
def open_firewall() -> tuple[bool, Optional[str]]:
    try:
        cmd = "netsh advfirewall set allprofiles state on"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        output = result.stdout
        logger.info(f"Firewall status: {output}")

        if result.returncode != 0:
            error_message = result.stderr or result.stdout or "Unknown error occurred"
            return False, error_message

        return True, None
    except Exception as e:
        error_msg = f"[open_firewall] Error opening firewall: {e}"
        logger.error(error_msg)
        return False, error_msg


def close_firewall() -> tuple[bool, Optional[str]]:
    try:
        cmd = "netsh advfirewall set allprofiles state off"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        output = result.stdout
        logger.info(f"Firewall status: {output}")

        if result.returncode != 0:
            error_message = result.stderr or result.stdout or "Unknown error occurred"
            return False, error_message

        return True, None
    except Exception as e:
        error_msg = f"[close_firewall] Error closing firewall: {e}"
        logger.error(error_msg)
        return False, error_msg


def send_command_result(command_id: str, error: Optional[str] = None) -> bool:
    """
    Send command execution result to server via HTTP POST request

    Args:
        command_id: The ID of the command that was executed
        error: Optional error message if command execution failed

    Returns:
        bool: True if the request was successful, False otherwise
    """
    try:
        # Skip if no command_id provided
        if not command_id:
            return True

        # ISO 8601 format with Z suffix (UTC timezone) similar to Laravel
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        result_data = {"command_id": command_id, "completed_at": completed_at}

        # Add error if exists
        if error:
            result_data["error"] = error

        logger.info(f"Sending command result: {json.dumps(result_data)}")

        response = requests.post(
            f"{APP_URL}{COMMAND_RESULT_ENDPOINT}", json=result_data
        )

        if response.status_code == 200:
            logger.info(f"Command result for {command_id} sent successfully")
            return True
        else:
            logger.error(
                f"Failed to send command result: {response.status_code} - {response.text}"
            )
            return False

    except Exception as e:
        logger.error(f"[send_command_result] Error sending command result: {e}")
        return False


def process_command(message: dict) -> bool:
    try:
        type = message.get("type", "")
        command_id = message.get("command_id", "")
        logger.info(f"Processing command: {type}")
        logger.debug(
            f"Raw command type: '{type}', length: {len(type)}, repr: {repr(type)}"
        )

        success = True
        error = None

        try:
            # Normalize command type for case insensitive comparison
            type_upper = type.strip().upper()
            logger.debug(f"Normalized command type: '{type_upper}'")

            if type_upper == "UPDATE":
                logger.info(
                    "Received update command. Initiating update process in a new thread..."
                )
                check_updates()
            elif type_upper == "FIREWALL_ON":
                logger.info("Received open firewall command. Opening firewall...")
                success, error_msg = open_firewall()
                if not success:
                    error = error_msg
            elif type_upper == "FIREWALL_OFF":
                logger.info("Received close firewall command. Closing firewall...")
                success, error_msg = close_firewall()
                if not success:
                    error = error_msg
            else:
                # Unknown command type
                success = False
                error = f"Unknown command type: {type}"
        except Exception as e:
            success = False
            error = str(e)

        # Send command result
        send_command_result(command_id, error if not success else None)

        return success
    except Exception as e:
        error_msg = f"[process_command] Error processing command: {e}"
        logger.error(error_msg)
        if command_id:
            send_command_result(command_id, error_msg)
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

        # Log detailed message format for debugging
        logger.debug(f"Raw message: {repr(body.decode('utf-8'))}")
        logger.info(f"Received message from {source}: {json.dumps(message, indent=2)}")

        # Get and validate 'type' field
        msg_type = message.get("type", "")
        logger.debug(
            f"Message type: '{msg_type}', type: {type(msg_type)}, repr: {repr(msg_type)}"
        )

        process_result = process_command(message)
        logger.debug(f"Command processing result: {process_result}")
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
        logger.debug("Queue bound to fanout exchange")

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
        logger.error(
            f"[start_command_listener] Error in command listener: {e}", exc_info=True
        )


# ===================== FILE HELPERS =====================


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


def download_update(version: str) -> str:
    try:
        response = requests.get(f"{APP_URL}{UPDATE_ENDPOINT}/{version}", stream=True)
        if response.status_code == 200:
            with open(AGENT_ZIP, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logger.info(f"Update package zip file saved to {AGENT_ZIP}")
            return AGENT_ZIP
        else:
            logger.error(
                f"[download_update] Failed to download update: {response.status_code} - {response.text}"
            )
            return None
    except Exception as e:
        logger.error(f"[download_update] Error downloading update: {e}")
        return None


def check_updates():
    # Simple version check
    local_version = open(VERSION_FILE_PATH).read().strip()
    response = requests.get(f"{APP_URL}{VERSION_ENDPOINT}")
    response.raise_for_status()  # Raise exception for bad status codes
    server_version = response.json()["latest_version"]

    if server_version != local_version:
        # Download update
        update_zip = download_update(server_version)

        # Create flag for restarter
        with open("restart.flag", "w") as f:
            f.write(server_version)

        # Exit for restart
        sys.exit(0)


# ===================== MAIN LOGIC =====================
def main() -> None:
    logger.info("Starting Lab Agent...")

    logger.info("Checking for updates...")
    check_updates()

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

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
