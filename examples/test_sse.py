#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SSE Server Test Client

This script tests the CHUK MCP SSE server by:
1. Connecting to the SSE endpoint
2. Sending a test message
3. Displaying the response

Usage:
    python test_sse.py [--host HOST] [--port PORT]
"""
import argparse
import asyncio
import json
import signal
import sys
import uuid
import time
from typing import Dict, Any

import httpx

# Global session ID used for both SSE connection and message posting
SESSION_ID = str(uuid.uuid4())

async def connect_to_sse(url: str):
    """Connect to SSE endpoint and listen for events."""
    # Add session_id as query parameter
    sse_url = f"{url}?session_id={SESSION_ID}"
    print(f"Connecting to SSE endpoint: {sse_url}")
    print(f"Using session ID: {SESSION_ID}")
    
    headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream('GET', sse_url, headers=headers, timeout=30.0) as response:
                if response.status_code != 200:
                    print(f"Error connecting to SSE: {response.status_code}")
                    return
                
                print(f"Connection established (status {response.status_code})")
                
                # Read and process events from the stream
                buffer = ""
                async for chunk in response.aiter_text():
                    print(f"Received chunk: {repr(chunk)}")
                    buffer += chunk
                    
                    # Process complete events
                    while "\n\n" in buffer:
                        event_text, buffer = buffer.split("\n\n", 1)
                        event_lines = event_text.strip().split("\n")
                        
                        # Simple parsing of SSE events
                        event_type = "message"  # Default
                        event_data = ""
                        
                        for line in event_lines:
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                event_data = line[5:].strip()
                        
                        if event_type == "message" and event_data:
                            try:
                                data = json.loads(event_data)
                                print(f"Received event: {json.dumps(data, indent=2)}")
                            except json.JSONDecodeError:
                                print(f"Received non-JSON data: {event_data}")
                        elif event_type == "error":
                            print(f"SSE Error: {event_data}")
                
    except asyncio.CancelledError:
        print("SSE listener cancelled")
    except Exception as e:
        print(f"Error in SSE listener: {e}")

async def send_test_message(url: str, tool_name: str):
    """Send a test message to the server."""
    print(f"Sending test message to: {url}")
    print(f"Using session ID: {SESSION_ID}")
    
    payload = {
        "id": SESSION_ID,
        "method": "callTool",
        "params": {
            "name": tool_name,
            "arguments": {
                "message": "Hello from SSE test client!"
            }
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, 
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Session-ID": SESSION_ID
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                print(f"Message sent successfully (status {response.status_code})")
                try:
                    response_json = response.json()
                    print(f"Response: {json.dumps(response_json, indent=2)}")
                except:
                    print(f"Response: {response.text}")
                return True
            else:
                print(f"Error sending message: {response.status_code}")
                print(f"Response: {response.text}")
                return False
    except Exception as e:
        print(f"Exception sending message: {e}")
        return False

async def run_test(host: str, port: int, sse_path: str, msg_path: str, tool_name: str):
    """Run the complete test."""
    base_url = f"http://{host}:{port}"
    sse_url = f"{base_url}{sse_path}"
    msg_url = f"{base_url}{msg_path}"
    
    # Start SSE listener in background
    listener_task = asyncio.create_task(connect_to_sse(sse_url))
    
    # Give the listener time to connect
    await asyncio.sleep(2)
    
    # Send test message
    await send_test_message(msg_url, tool_name)
    
    # Keep listening for a while
    try:
        await asyncio.sleep(10)  # Listen for 10 seconds
    except asyncio.CancelledError:
        pass
    
    # Clean up
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test CHUK MCP SSE Server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--sse-path", default="/sse", help="SSE endpoint path")
    parser.add_argument("--msg-path", default="/messages", help="Messages endpoint path")
    parser.add_argument("--tool", default="echo", help="Tool to test")
    return parser.parse_args()

async def main():
    """Main entry point."""
    args = parse_args()
    
    # Handle Ctrl+C gracefully
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(loop)))
        except NotImplementedError:
            # Windows doesn't support SIGINT/SIGTERM handlers
            pass
    
    await run_test(
        host=args.host,
        port=args.port,
        sse_path=args.sse_path,
        msg_path=args.msg_path,
        tool_name=args.tool
    )

async def shutdown(loop):
    """Shutdown the event loop gracefully."""
    print("Shutting down...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted by user")
        sys.exit(1)