#!/usr/bin/env python
"""
RabbitMQ Command Receiver

This script connects to a RabbitMQ server and listens for command messages from a Laravel application.
It extracts command data from PHP serialized messages and processes them accordingly.
The script uses a topic exchange to filter messages based on routing keys provided as command line arguments.
"""
import json
import sys
import requests

import pika

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
    Extract command data from JSON message

    Args:
        serialized_data (str): The JSON data from the message

    Returns:
        dict: Extracted command data or error information
    """
    try:
        # Parse the JSON data
        data = json.loads(serialized_data)

        # Check if all required fields are present
        if "data" in data and all(
            key in data["data"] for key in ["id", "machine_id", "command_type"]
        ):
            return {
                "id": data["data"]["id"],
                "machine_id": data["data"]["machine_id"],
                "command_type": data["data"]["command_type"],
            }

        return {"error": "Missing required command data fields"}
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
    print(" [x] Received message body: ", body)
    # Convert binary message body to UTF-8 string
    decoded_body = body.decode("utf-8")
    # Extract structured command data from the JSON message
    command_data = extract_command_data(decoded_body)
    print(f" [x] Received command: {command_data}")

    # Send the command result to the specified URL
    url = "http://localhost:8000/api/agent/command_result"
    headers = {"Content-Type": "application/json"}
    command_result = {
        "command_id": command_data["id"],
        "status": "done",
    }
    print(f" [x] Sending command result: {command_result}")
    # Send a POST request with the command result as JSON
    response = requests.post(url, json=command_result, headers=headers)
    # Print the response status code for debugging
    print(f" [x] Response status code: {response.status_code}")


# Configure the consumer to use our callback function when messages arrive
# auto_ack=True means messages are acknowledged automatically when processed
channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)

# Start consuming messages - this blocks until CTRL+C or the channel is closed
channel.start_consuming()
