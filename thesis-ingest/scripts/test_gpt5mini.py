#!/usr/bin/env python3
"""
Minimal test script for OpenClaw Copilot GPT-5 mini with image input.
Uses only Python standard library.
"""

import argparse
import json
import os
import subprocess
import sys


def find_default_image(input_dir: str) -> str | None:
    """Find a sensible image file in the input directory."""
    if not os.path.isdir(input_dir):
        return None
    # Prefer common image extensions, pick first match
    for filename in sorted(os.listdir(input_dir)):
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            return os.path.join(input_dir, filename)
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Test OpenClaw GPT-5-mini with image input"
    )
    parser.add_argument(
        "--image",
        help="Path to image file to describe",
        default=None,
    )
    args = parser.parse_args()

    # Determine image path
    if args.image:
        image_path = args.image
    else:
        default_dir = "os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "input_images")"
        image_path = find_default_image(default_dir)
        if not image_path:
            print(f"Error: No image found in {default_dir}", file=sys.stderr)
            print("Please provide --image <path>", file=sys.stderr)
            sys.exit(1)

    if not os.path.isfile(image_path):
        print(f"Error: Image file not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    # Model specification
    model = "github-copilot/gpt-5-mini"

    # Build the OpenClaw CLI command for image description
    cmd = [
        "openclaw",
        "infer", "image", "describe",
        "--file", image_path,
        "--model", model,
        "--json",
    ]

    # Run the command
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Check command failure
    if result.returncode != 0:
        print("Error: OpenClaw command failed", file=sys.stderr)
        print("\n--- STDOUT ---", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print("\n--- STDERR ---", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    # Try to parse JSON output
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON response: {e}", file=sys.stderr)
        print("\n--- STDOUT ---", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print("\n--- STDERR ---", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    # Extract and print the model's text response
    if isinstance(output, dict):
        # Try common response fields
        text = (
            output.get("text")
            or output.get("content")
            or output.get("response")
            or output.get("message")
            or output.get("description")
        )
        if text:
            print(text)
        else:
            # Print the whole response if no known field
            print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(output)


if __name__ == "__main__":
    main()
