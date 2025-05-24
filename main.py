import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
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
def open_firewall() -> tuple[bool, str]:
    try:
        cmd = "netsh advfirewall set allprofiles state on"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        output = result.stdout
        logger.info(f"Firewall status: {output}")

        if result.returncode != 0:
            error_message = result.stderr or result.stdout or "Unknown error occurred"
            return False, error_message

        return True, output
    except Exception as e:
        error_msg = f"[open_firewall] Error opening firewall: {e}"
        logger.error(error_msg)
        return False, output


def close_firewall() -> tuple[bool, str]:
    try:
        cmd = "netsh advfirewall set allprofiles state off"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        output = result.stdout
        logger.info(f"Firewall status: {output}")

        if result.returncode != 0:
            error_message = result.stderr or result.stdout or "Unknown error occurred"
            return False, error_message

        return True, output
    except Exception as e:
        error_msg = f"[close_firewall] Error closing firewall: {e}"
        logger.error(error_msg)
        return False, error_msg


def remove_website_block(websites_to_unblock: list) -> tuple[bool, str]:
    try:
        with open(r"C:\Windows\System32\drivers\etc\hosts", "r+") as file:
            lines = file.readlines()
            file.seek(0)
            removed_sites = []
            for line in lines:
                line_written = False
                for website in websites_to_unblock:
                    if f"127.0.0.1 {website}" in line:
                        removed_sites.append(website)
                        line_written = True
                        break
                if not line_written:
                    file.write(line)
            file.truncate()

            if removed_sites:
                return (
                    True,
                    f"Successfully unblocked websites: {', '.join(removed_sites)}",
                )
            else:
                return True, "No websites were found to unblock"
    except Exception as e:
        error_msg = f"[remove_website_block] Error unblocking websites: {e}"
        logger.error(error_msg)
        return False, error_msg


def block_website(websites_to_block: list) -> tuple[bool, str]:
    try:
        with open(r"C:\Windows\System32\drivers\etc\hosts", "a+") as file:
            file.seek(0)
            content = file.read()
            blocked_sites = []
            for website in websites_to_block:
                if f"127.0.0.1 {website}" not in content:
                    file.seek(0, 2)  # Move to end of file
                    file.write(f"127.0.0.1 {website}\n")
                    blocked_sites.append(website)

            if blocked_sites:
                return (
                    True,
                    f"Successfully blocked websites: {', '.join(blocked_sites)}",
                )
            else:
                return True, "All websites were already blocked"
    except Exception as e:
        error_msg = f"[block_website] Error blocking websites: {e}"
        logger.error(error_msg)
        return False, error_msg


def execute_custom_command(name: str, args: list) -> tuple[bool, Optional[str]]:
    try:
        cmd = f"{name} {args}"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        stdout = result.stdout

        if result.returncode != 0:
            error_message = result.stderr or stdout or "Unknown error occurred"
            return False, error_message
        return True, stdout
    except Exception as e:
        return False, str(e)


def send_command_result(
    command_id: str, error: Optional[str] = None, output: Optional[str] = None
) -> bool:
    """
    Send command execution result to server via HTTP POST request

    Args:
        command_id: The ID of the command that was executed
        error: Optional error message if command execution failed
        output: Optional output message if command execution succeeded

    Returns:
        bool: True if the request was successful, False otherwise
    """
    try:
        # Skip if no command_id provided
        if not command_id:
            return True

        logger.debug(
            f"send_command_result called with - command_id: {command_id}, error: {error}, output: {output}"
        )

        # ISO 8601 format with Z suffix (UTC timezone) similar to Laravel
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        result_data = {"command_id": command_id, "completed_at": completed_at}

        # Add error if exists
        if error:
            result_data["error"] = error
            logger.debug(f"Added error to result_data: {error}")

        # Add output if exists and no error
        if output is not None and not error:
            result_data["output"] = output
            logger.debug(f"Added output to result_data: {output}")

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
        logger.info(f"Processing command: {message}")
        type = message.get("type", "")
        command_id = message.get("command_id", "")
        params = message.get("params", {})
        logger.info(f"Processing command: {type}")
        logger.debug(
            f"Raw command type: '{type}', length: {len(type)}, repr: {repr(type)}"
        )
        logger.info(f"Command params: {params}")

        success = True
        error = None
        output = None

        try:
            # Normalize command type for case insensitive comparison
            type_upper = type.strip().upper()
            logger.debug(f"Normalized command type: '{type_upper}'")

            if type_upper == "UPDATE":
                logger.info(
                    "Received update command. Initiating update process in a new thread..."
                )
                check_updates()
                output = "Update process initiated"
            elif type_upper == "FIREWALL_ON":
                logger.info("Received open firewall command. Opening firewall...")
                success, msg = open_firewall()
                if success:
                    output = msg
                else:
                    error = msg
            elif type_upper == "FIREWALL_OFF":
                logger.info("Received close firewall command. Closing firewall...")
                success, msg = close_firewall()
                if success:
                    output = msg
                else:
                    error = msg
            elif type_upper == "BLOCK_WEBSITE":
                logger.info("Received block website command. Blocking website...")
                urls = params.get("urls", [])
                success, msg = block_website(urls)
                if success:
                    output = msg
                else:
                    error = msg
            elif type_upper == "UNBLOCK_WEBSITE":
                logger.info("Received unblock website command. Unblocking website...")
                urls = params.get("urls", [])
                success, msg = remove_website_block(urls)
                if success:
                    output = msg
                else:
                    error = msg
            elif type_upper == "CUSTOM":
                logger.info("Received custom command. Executing custom command...")
                name = params.get("name", "")
                args = params.get("args", [])
                success, msg = execute_custom_command(name, args)
                if success:
                    output = msg
                else:
                    error = msg
            else:
                # Unknown command type
                success = False
                error = f"Unknown command type: {type}"
        except Exception as e:
            success = False
            error = str(e)

        # Send command result with output for success or error for failure
        logger.debug(
            f"Command processing complete - success: {success}, error: {error}, output: {output}"
        )
        send_command_result(
            command_id, error if not success else None, output if success else None
        )

        return success
    except Exception as e:
        error_msg = f"[process_command] Error processing command: {e}"
        logger.error(error_msg)
        if command_id:
            send_command_result(command_id, error_msg, None)
        return False


def command_callback(
    ch, method, properties, body, computer_id: str, room_id: str
) -> None:
    try:
        message = json.loads(body.decode("utf-8"))
        print(message)
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


# ===================== UPDATER =====================


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
    # check_updates()

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
