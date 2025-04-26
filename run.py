#!/usr/bin/env python
"""
Entry point script for Lab Agent.
This script provides a convenient way to run the application from the root directory.
"""
import os
import sys
import logging

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


def main():
    """Run the application by importing and calling the main module."""
    try:
        # Import the main module from lab-agent-core
        from lab_agent_core.main import main as core_main

        # Run the main function
        core_main()
    except ImportError:
        # Fall back to the old path if there's an issue
        try:
            from lab_agent_core import main as core_main

            core_main.main()
        except ImportError:
            # If all else fails, try running main.py directly
            try:
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    "main", os.path.join("lab-agent-core", "main.py")
                )
                main_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(main_module)
                main_module.main()
            except Exception as e:
                print(f"Error: Unable to run the application. {str(e)}")
                sys.exit(1)


if __name__ == "__main__":
    main()
