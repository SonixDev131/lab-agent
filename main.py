import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from io import BytesIO
from typing import Optional, Tuple

import pika
import psutil
import requests
from PIL import ImageGrab

# Add alternative screenshot imports
try:
    import mss

    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    import pyautogui

    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

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
APP_URL = "http://13.250.24.210"
VERSION_FILE = "version.txt"
REGISTER_ENDPOINT = "/api/agents/register"
UPDATE_ENDPOINT = "/api/agent/update"
VERSION_ENDPOINT = "/api/agent/version"
COMMAND_RESULT_ENDPOINT = "/api/agent/command-result"
SCREENSHOT_ENDPOINT = "/api/agent/screenshot"
RABBITMQ_URL = "amqp://guest:guest@13.250.24.210:5672/"
SERVICE_NAME = "agent"  # or your actual service name
UPDATER_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(UPDATER_DIR, "agent_config.json")
ZIP_PATH = os.path.join(UPDATER_DIR, AGENT_ZIP)
EXTRACT_DIR = os.path.join(UPDATER_DIR, UPDATE_TEMP)
VERSION_FILE_PATH = os.path.join(UPDATER_DIR, VERSION_FILE)
RESTART_FLAG_PATH = os.path.join(UPDATER_DIR, "restart.flag")
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


def download_installer(
    installer_id: str,
    installer_name: str,
    download_url: str,
    auto_install: bool = False,
    install_args: list = None,
) -> tuple[bool, str]:
    """
    Download an installer using the API endpoint and optionally auto-install it

    Args:
        installer_id: Unique identifier for the installer
        installer_name: Name/filename for the installer
        download_url: URL to download the installer from (legacy parameter, now unused)
        auto_install: Whether to automatically run the installer after download
        install_args: Additional arguments to pass to the installer

    Returns:
        tuple[bool, str]: (success, message)
    """
    if install_args is None:
        install_args = []

    try:
        logger.info(
            f"Starting download of installer: {installer_name} (ID: {installer_id})"
        )

        # Validate installer_id
        if not installer_id:
            return False, "Installer ID is required"

        # Check available disk space (at least 500MB free for installers)
        disk_usage = psutil.disk_usage(".")
        free_space_mb = disk_usage.free / (1024 * 1024)
        if free_space_mb < 500:
            return (
                False,
                f"Insufficient disk space: {free_space_mb:.1f}MB free, need at least 500MB",
            )

        # Create downloads directory if it doesn't exist
        downloads_dir = os.path.join(UPDATER_DIR, "downloads")
        os.makedirs(downloads_dir, exist_ok=True)

        # Construct API URL for installer download
        api_url = f"{APP_URL}/api/agent/installer/{installer_id}"
        logger.info(f"Downloading from API: {api_url}")

        # Download the file from API
        response = requests.get(
            api_url,
            stream=True,
            timeout=300,  # 5 minute timeout
            headers={"User-Agent": "Lab-Agent/1.0"},
        )

        if response.status_code != 200:
            return (
                False,
                f"Failed to download installer from API: HTTP {response.status_code}",
            )

        # Get filename from Content-Disposition header or use installer_name
        filename = installer_name
        if "content-disposition" in response.headers:
            import re

            cd_header = response.headers["content-disposition"]
            filename_match = re.search(r"filename[*]?=([^;]+)", cd_header)
            if filename_match:
                filename = filename_match.group(1).strip("\"'")

        # Fallback to installer_name or generate filename
        if not filename:
            filename = f"{installer_name or f'installer_{installer_id}'}.exe"

        file_path = os.path.join(downloads_dir, filename)

        logger.info(f"Saving installer to: {file_path}")

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    # Log progress every 10MB
                    if downloaded % (10 * 1024 * 1024) == 0:
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            logger.info(f"Download progress: {progress:.1f}%")

        # Verify file was downloaded successfully
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return False, "Download failed: File not found or empty"

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        logger.info(f"Successfully downloaded {filename} ({file_size_mb:.1f}MB)")

        result_msg = f"Successfully downloaded {filename} ({file_size_mb:.1f}MB)"

        return True, result_msg

    except requests.exceptions.Timeout:
        return False, "Download timeout after 5 minutes"
    except requests.exceptions.RequestException as e:
        return False, f"Network error during download: {str(e)}"
    except Exception as e:
        logger.error(f"[download_installer] Error downloading installer: {e}")
        return False, f"Error downloading installer: {str(e)}"


def take_screenshot(quality: int = 85) -> tuple[bool, Optional[BytesIO], Optional[str]]:
    """
    Take a screenshot of the current desktop

    Args:
        quality: JPEG quality (1-100, default 85)

    Returns:
        tuple[bool, Optional[BytesIO], Optional[str]]: (success, image_buffer, error_message)
    """
    try:
        logger.info("Taking screenshot...")

        # Check if we're in Session 0 (service context)
        import ctypes

        session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        current_session = ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid())
        logger.info(
            f"Current session: {current_session}, Active console session: {session_id}"
        )

        if current_session == 0:
            logger.warning(
                "Running in Session 0 - screenshot may fail due to session isolation"
            )

        # Take screenshot using PIL
        screenshot = ImageGrab.grab()

        if screenshot is None:
            error_details = []

            # Check for common causes
            if current_session == 0:
                error_details.append(
                    "Session 0 isolation (service cannot access user desktop)"
                )

            # Check if display is available
            try:
                import tkinter as tk

                root = tk.Tk()
                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()
                root.destroy()
                if screen_width <= 0 or screen_height <= 0:
                    error_details.append("Invalid screen dimensions")
            except Exception as display_error:
                error_details.append(f"Display access error: {display_error}")

            error_msg = (
                "Failed to capture screenshot. Possible causes: "
                + "; ".join(error_details)
                if error_details
                else "Unknown screenshot capture failure"
            )
            return False, None, error_msg

        # Convert to RGB if needed (remove alpha channel for JPEG)
        if screenshot.mode == "RGBA":
            screenshot = screenshot.convert("RGB")

        # Create BytesIO buffer
        img_buffer = BytesIO()

        # Save screenshot as JPEG to buffer
        screenshot.save(img_buffer, format="JPEG", quality=quality, optimize=True)
        img_buffer.seek(0)

        # Get image size info
        img_size_mb = len(img_buffer.getvalue()) / (1024 * 1024)
        logger.info(
            f"Screenshot captured successfully. Size: {img_size_mb:.2f}MB, Resolution: {screenshot.size}"
        )

        return True, img_buffer, None

    except ImportError as e:
        error_msg = f"[take_screenshot] Missing dependency: {e}"
        logger.error(error_msg)
        return False, None, error_msg
    except PermissionError as e:
        error_msg = f"[take_screenshot] Permission denied: {e}. Service may need 'Interact with desktop' permission"
        logger.error(error_msg)
        return False, None, error_msg
    except OSError as e:
        error_msg = f"[take_screenshot] System error: {e}. Check graphics drivers and display configuration"
        logger.error(error_msg)
        return False, None, error_msg
    except Exception as e:
        error_msg = f"[take_screenshot] Error taking screenshot: {e}"
        logger.error(error_msg)
        return False, None, error_msg


def take_screenshot_mss(
    quality: int = 85,
) -> tuple[bool, Optional[BytesIO], Optional[str]]:
    """
    Alternative screenshot method using mss library

    Args:
        quality: JPEG quality (1-100, default 85)

    Returns:
        tuple[bool, Optional[BytesIO], Optional[str]]: (success, image_buffer, error_message)
    """
    if not MSS_AVAILABLE:
        return False, None, "mss library not available"

    try:
        logger.info("Taking screenshot using mss...")

        with mss.mss() as sct:
            # Capture all monitors or just the first one
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            screenshot = sct.grab(monitor)

            # Convert to PIL Image
            from PIL import Image

            img = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )

            # Create BytesIO buffer
            img_buffer = BytesIO()
            img.save(img_buffer, format="JPEG", quality=quality, optimize=True)
            img_buffer.seek(0)

            img_size_mb = len(img_buffer.getvalue()) / (1024 * 1024)
            logger.info(
                f"Screenshot (mss) captured successfully. Size: {img_size_mb:.2f}MB, Resolution: {img.size}"
            )

            return True, img_buffer, None

    except Exception as e:
        error_msg = f"[take_screenshot_mss] Error: {e}"
        logger.error(error_msg)
        return False, None, error_msg


def take_screenshot_pyautogui(
    quality: int = 85,
) -> tuple[bool, Optional[BytesIO], Optional[str]]:
    """
    Alternative screenshot method using pyautogui

    Args:
        quality: JPEG quality (1-100, default 85)

    Returns:
        tuple[bool, Optional[BytesIO], Optional[str]]: (success, image_buffer, error_message)
    """
    if not PYAUTOGUI_AVAILABLE:
        return False, None, "pyautogui library not available"

    try:
        logger.info("Taking screenshot using pyautogui...")

        screenshot = pyautogui.screenshot()

        if screenshot is None:
            return False, None, "pyautogui screenshot returned None"

        # Convert to RGB if needed
        if screenshot.mode == "RGBA":
            screenshot = screenshot.convert("RGB")

        # Create BytesIO buffer
        img_buffer = BytesIO()
        screenshot.save(img_buffer, format="JPEG", quality=quality, optimize=True)
        img_buffer.seek(0)

        img_size_mb = len(img_buffer.getvalue()) / (1024 * 1024)
        logger.info(
            f"Screenshot (pyautogui) captured successfully. Size: {img_size_mb:.2f}MB, Resolution: {screenshot.size}"
        )

        return True, img_buffer, None

    except Exception as e:
        error_msg = f"[take_screenshot_pyautogui] Error: {e}"
        logger.error(error_msg)
        return False, None, error_msg


def take_screenshot_winapi(
    quality: int = 85,
) -> tuple[bool, Optional[BytesIO], Optional[str]]:
    """
    Alternative screenshot method using Windows API

    Args:
        quality: JPEG quality (1-100, default 85)

    Returns:
        tuple[bool, Optional[BytesIO], Optional[str]]: (success, image_buffer, error_message)
    """
    try:
        logger.info("Taking screenshot using Windows API...")

        import ctypes
        from ctypes import wintypes

        # Get screen dimensions
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        screen_width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_height = user32.GetSystemMetrics(1)  # SM_CYSCREEN

        if screen_width <= 0 or screen_height <= 0:
            return False, None, "Invalid screen dimensions from Windows API"

        # Create device contexts
        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

        # Create bitmap
        hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, screen_width, screen_height)
        gdi32.SelectObject(hdc_mem, hbitmap)

        # Copy screen to bitmap
        gdi32.BitBlt(
            hdc_mem, 0, 0, screen_width, screen_height, hdc_screen, 0, 0, 0x00CC0020
        )  # SRCCOPY

        # Get bitmap info
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = screen_width
        bmi.biHeight = -screen_height  # Negative for top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 24
        bmi.biCompression = 0  # BI_RGB

        # Calculate buffer size
        buffer_size = screen_width * screen_height * 3  # 24-bit RGB
        buffer = (ctypes.c_ubyte * buffer_size)()

        # Get DIB bits
        result = gdi32.GetDIBits(
            hdc_screen, hbitmap, 0, screen_height, buffer, ctypes.byref(bmi), 0
        )

        # Clean up
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

        if result == 0:
            return False, None, "GetDIBits failed"

        # Convert to PIL Image
        from PIL import Image

        img = Image.frombuffer(
            "RGB", (screen_width, screen_height), buffer, "raw", "BGR", 0, 1
        )

        # Create BytesIO buffer
        img_buffer = BytesIO()
        img.save(img_buffer, format="JPEG", quality=quality, optimize=True)
        img_buffer.seek(0)

        img_size_mb = len(img_buffer.getvalue()) / (1024 * 1024)
        logger.info(
            f"Screenshot (WinAPI) captured successfully. Size: {img_size_mb:.2f}MB, Resolution: {img.size}"
        )

        return True, img_buffer, None

    except Exception as e:
        error_msg = f"[take_screenshot_winapi] Error: {e}"
        logger.error(error_msg)
        return False, None, error_msg


def take_screenshot_with_fallbacks(
    quality: int = 85,
) -> tuple[bool, Optional[BytesIO], Optional[str]]:
    """
    Try multiple screenshot methods with fallbacks

    Args:
        quality: JPEG quality (1-100, default 85)

    Returns:
        tuple[bool, Optional[BytesIO], Optional[str]]: (success, image_buffer, error_message)
    """
    methods = [
        ("PIL ImageGrab", take_screenshot),
        ("MSS Library", take_screenshot_mss),
        ("PyAutoGUI", take_screenshot_pyautogui),
        ("Windows API", take_screenshot_winapi),
    ]

    errors = []

    for method_name, method_func in methods:
        try:
            logger.info(f"Trying screenshot method: {method_name}")
            success, img_buffer, error = method_func(quality)

            if success and img_buffer:
                logger.info(f"Screenshot successful using {method_name}")
                return True, img_buffer, None
            else:
                error_msg = f"{method_name}: {error or 'Unknown error'}"
                errors.append(error_msg)
                logger.warning(f"Screenshot method {method_name} failed: {error}")

        except Exception as e:
            error_msg = f"{method_name}: Exception - {e}"
            errors.append(error_msg)
            logger.error(f"Screenshot method {method_name} exception: {e}")

    # All methods failed
    combined_error = "All screenshot methods failed. Errors: " + " | ".join(errors)
    logger.error(combined_error)
    return False, None, combined_error


def upload_screenshot(
    command_id: str, computer_id: str, screenshot_buffer: BytesIO
) -> tuple[bool, str]:
    """
    Upload screenshot to server

    Args:
        command_id: Command ID that requested the screenshot
        computer_id: Computer ID
        screenshot_buffer: BytesIO buffer containing the screenshot

    Returns:
        tuple[bool, str]: (success, message)
    """
    try:
        logger.info(f"Uploading screenshot for command_id: {command_id}")

        # Prepare the current timestamp in ISO format
        taken_at = datetime.now().isoformat()

        # Prepare form data
        files = {"screenshot": ("screenshot.jpg", screenshot_buffer, "image/jpeg")}

        data = {
            "command_id": command_id,
            "computer_id": computer_id,
            "taken_at": taken_at,
        }

        logger.debug(f"Upload data: {data}")

        # Send POST request to upload screenshot
        response = requests.post(
            f"{APP_URL}{SCREENSHOT_ENDPOINT}",
            files=files,
            data=data,
            timeout=60,  # 1 minute timeout for screenshot upload
        )

        if response.status_code == 200:
            logger.info(
                f"Screenshot uploaded successfully for command_id: {command_id}"
            )
            return True, "Screenshot uploaded successfully"
        else:
            error_msg = f"Failed to upload screenshot: HTTP {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg

    except requests.exceptions.Timeout:
        error_msg = "Upload timeout after 1 minute"
        logger.error(f"[upload_screenshot] {error_msg}")
        return False, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error during upload: {str(e)}"
        logger.error(f"[upload_screenshot] {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Error uploading screenshot: {str(e)}"
        logger.error(f"[upload_screenshot] {error_msg}")
        return False, error_msg


def capture_and_send_screenshot(
    command_id: str, computer_id: str, quality: int = 85
) -> tuple[bool, str]:
    """
    Complete workflow to capture screenshot and send to server

    Args:
        command_id: Command ID that requested the screenshot
        computer_id: Computer ID
        quality: JPEG quality (1-100, default 85)

    Returns:
        tuple[bool, str]: (success, message)
    """
    try:
        # Take screenshot
        success, img_buffer, error = take_screenshot_with_fallbacks(quality)

        if not success:
            return False, error or "Failed to take screenshot"

        # Upload screenshot
        success, message = upload_screenshot(command_id, computer_id, img_buffer)

        # Clean up buffer
        if img_buffer:
            img_buffer.close()

        return success, message

    except Exception as e:
        error_msg = f"[capture_and_send_screenshot] Error in screenshot workflow: {e}"
        logger.error(error_msg)
        return False, error_msg


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
            elif type_upper == "DOWNLOAD_INSTALLER":
                logger.info(
                    "Received download_installer command. Processing download installer..."
                )
                installer_id = message.get("installer_id", "")
                installer_name = message.get("installer_name", "")
                download_url = message.get("download_url", "")
                auto_install = message.get("auto_install", False)
                install_args = message.get("install_args", [])
                logger.info(
                    f"Download params - ID: {installer_id}, Name: {installer_name}, URL: {download_url}, Auto-install: {auto_install}"
                )
                success, msg = download_installer(
                    installer_id,
                    installer_name,
                    download_url,
                    auto_install,
                    install_args,
                )
                if success:
                    output = msg
                else:
                    error = msg
            elif type_upper == "SCREENSHOT":
                logger.info(
                    "Received screenshot command. Taking and uploading screenshot..."
                )
                # Get computer_id from config for screenshot upload
                config = get_config_info()
                computer_id_for_screenshot = config.get("computer_id")

                if not computer_id_for_screenshot:
                    success = False
                    error = "Computer ID not found in config"
                else:
                    # Get quality parameter (optional, default 85)
                    quality = params.get("quality", 85)
                    if not isinstance(quality, int) or quality < 1 or quality > 100:
                        quality = 85

                    success, msg = capture_and_send_screenshot(
                        command_id, computer_id_for_screenshot, quality
                    )
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


def download_update(version: str) -> bool:
    try:
        # Check available disk space (at least 100MB free)
        disk_usage = psutil.disk_usage(".")
        free_space_mb = disk_usage.free / (1024 * 1024)
        if free_space_mb < 100:
            logger.error(
                f"Insufficient disk space: {free_space_mb:.1f}MB free, need at least 100MB"
            )
            return False

        logger.info(f"Downloading update version {version}...")
        response = requests.get(
            f"{APP_URL}{UPDATE_ENDPOINT}/{version}",
            stream=True,
            timeout=300,  # 5 minute timeout
        )
        if response.status_code == 200:
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(ZIP_PATH, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        # Log progress every 1MB
                        if downloaded % (1024 * 1024) == 0:
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                logger.info(f"Download progress: {progress:.1f}%")

            logger.info(
                f"Update package zip file saved to {ZIP_PATH} ({downloaded} bytes)"
            )
            return True
        else:
            logger.error(
                f"[download_update] Failed to download update: {response.status_code} - {response.text}"
            )
            return False
    except requests.exceptions.Timeout:
        logger.error("[download_update] Download timeout after 5 minutes")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"[download_update] Network error during download: {e}")
        return False
    except Exception as e:
        logger.error(f"[download_update] Error downloading update: {e}")
        return False


def check_updates():
    try:
        # Simple version check
        logger.info(f"Reading version from: {VERSION_FILE_PATH}")

        if not os.path.exists(VERSION_FILE_PATH):
            logger.error(f"Version file {VERSION_FILE_PATH} does not exist!")
            return

        local_version = open(VERSION_FILE_PATH).read().strip()
        logger.info(f"Local version: '{local_version}'")

        response = requests.get(f"{APP_URL}{VERSION_ENDPOINT}")
        response.raise_for_status()  # Raise exception for bad status codes
        server_version = response.json()["latest_version"]
        logger.info(f"Server version: '{server_version}'")

        if server_version != local_version:
            logger.info(f"Update available: {local_version} -> {server_version}")

            # Download update and check if successful
            download_result = download_update(server_version)

            if not download_result:
                logger.error("Failed to download update. Aborting update process.")
                return

            # Verify the downloaded file exists and is valid
            if not os.path.exists(ZIP_PATH):
                logger.error(f"Downloaded file {ZIP_PATH} not found. Aborting update.")
                return

            # Check file size (should be > 0)
            if os.path.getsize(ZIP_PATH) == 0:
                logger.error(f"Downloaded file {ZIP_PATH} is empty. Aborting update.")
                os.remove(ZIP_PATH)  # Remove corrupted file
                return

            logger.info("Download successful. Creating restart flag...")

            # Create flag for restarter only after successful download
            with open(RESTART_FLAG_PATH, "w") as f:
                f.write(server_version)

            logger.info("Update process initiated. Exiting for restart...")
            # Exit for restart
            sys.exit(0)
        else:
            logger.info(f"Already on latest version: {local_version}")
    except Exception as e:
        logger.error(f"[check_updates] Error checking for updates: {e}")
        # Don't exit on error, continue with current version


# ===================== MAIN LOGIC =====================
def ensure_correct_working_directory():
    """Ensure we're running from the correct directory"""
    try:
        # Change to the script's directory
        os.chdir(UPDATER_DIR)
        logger.info(f"Working directory changed to: {UPDATER_DIR}")
    except Exception as e:
        logger.error(f"Failed to change working directory: {e}")


def main() -> None:
    # First, ensure we're in the correct directory
    ensure_correct_working_directory()

    print("Starting Lab Agent...")
    logger.info("Starting Lab Agent...")
    logger.info(f"Script directory: {UPDATER_DIR}")
    logger.info(f"Working directory: {os.getcwd()}")

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
