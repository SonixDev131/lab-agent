#!/usr/bin/env python
"""
RabbitMQ Command Receiver

This script connects to a RabbitMQ server and listens for command messages from a Laravel application.
It extracts command data from PHP serialized messages and processes them accordingly.
The script uses a topic exchange to filter messages based on routing keys provided as command line arguments.
"""
import json
import re
import sys

import pika
from phpserialize import *

# Establish connection to RabbitMQ server using CloudAMQP hosting
connection = pika.BlockingConnection(
    pika.URLParameters(
        "amqps://aizfhyyx:LZhALcBsyDLc1pqBJNowAzFWJ_GsaSBw@armadillo.rmq.cloudamqp.com/aizfhyyx"
    )
)
channel = connection.channel()

# Declare the exchange that matches the one used by the Laravel application
# Topic exchange type allows filtering messages based on routing patterns
channel.exchange_declare(
    exchange="agent_command_exchange", exchange_type="topic", durable=True
)

# Create a temporary queue that will be deleted when the connection closes
# exclusive=True ensures this queue is used only by this connection
result = channel.queue_declare("", exclusive=True)
queue_name = result.method.queue

# Process command line arguments as routing keys for message filtering
# Example: python receive_logs_topic.py "agent.command.#" "machine.123"
binding_keys = sys.argv[1:]
if not binding_keys:
    sys.stderr.write("Usage: %s [binding_key]...\n" % sys.argv[0])
    sys.exit(1)

# Bind the temporary queue to the exchange for each routing key specified
# This determines which messages this consumer will receive
for binding_key in binding_keys:
    channel.queue_bind(
        exchange="agent_command_exchange", queue=queue_name, routing_key=binding_key
    )

print(" [*] Waiting for commands. To exit press CTRL+C")


def extract_command_data(serialized_data):
    """
    Extract command data from Laravel's serialized job format

    The data comes in a nested format:
    1. Outer JSON wrapper
    2. Inside that, a PHP-serialized string containing command details
    3. Within the PHP data, we extract specific command properties

    Args:
        serialized_data (str): The JSON+PHP serialized data from Laravel

    Returns:
        dict: Extracted command data or error information
    """
    try:
        # Parse the JSON outer wrapper first
        data = json.loads(serialized_data)

        # Look for the serialized PHP command data in the expected location
        if "data" in data and "command" in data["data"]:
            php_data = data["data"]["command"]

            # Use regex to extract specific fields from PHP serialized format
            # This approach is used because the standard phpserialize library
            # may not fully handle Laravel's specific serialization format
            command_match = re.search(r'commandData";a:\d+:{(.*?)}', php_data)
            if command_match:
                command_part = command_match.group(1)

                # Extract individual command properties with regex
                # Format follows PHP serialization: s:keyLength:"keyName";s:valueLength:"value"
                id_match = re.search(r's:2:"id";s:\d+:"(.*?)"', command_part)
                machine_id_match = re.search(
                    r's:10:"machine_id";s:\d+:"(.*?)"', command_part
                )
                command_type_match = re.search(
                    r's:12:"command_type";s:\d+:"(.*?)"', command_part
                )

                # Construct and return the extracted data if all fields were found
                if id_match and machine_id_match and command_type_match:
                    return {
                        "id": id_match.group(1),
                        "machine_id": machine_id_match.group(1),
                        "command_type": command_type_match.group(1),
                    }

        return {"error": "Could not parse command data"}
    except Exception as e:
        # Return error information if any exception occurs during parsing
        return {"error": str(e)}


def callback(ch, method, properties, body):
    """
    Process each message received from RabbitMQ

    Args:
        ch: Channel object
        method: Contains delivery information like routing key
        properties: Message properties
        body: Message content (bytes)
    """
    # Convert binary message body to UTF-8 string
    decoded_body = body.decode("utf-8")
    # Extract structured command data from the serialized message
    command_data = extract_command_data(decoded_body)
    print(f" [x] Received command: {command_data}")


# Configure the consumer to use our callback function when messages arrive
# auto_ack=True means messages are acknowledged automatically when processed
channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)

# Start consuming messages - this blocks until CTRL+C or the channel is closed
channel.start_consuming()
