import asyncio
import httpx
import websockets
import json

async def listen_ws():
    uri = "ws://localhost:8000/ws/trace"
    print(f"Connecting to WebSocket at {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket successfully! Listening for traces...")
            while True:
                message = await websocket.recv()
                data = json.loads(message)
                # Ignore ping keepalives
                if data.get("type") == "ping":
                    continue
                print(f"\n[WS RECEIVE] -> Type: {data.get('type')}, Step ID: {data.get('step_id')}, Agent: {data.get('agent')}, Description: {data.get('description', '')[:60]}...")
                if 'confidence' in data:
                    print(f"               Confidence: {data.get('confidence')}, Verification Passed: {data.get('verification_passed')}")
    except asyncio.CancelledError:
        print("WebSocket listener task stopped.")
    except Exception as e:
        print(f"WebSocket Error: {e}")

async def send_chat():
    # Wait for the WebSocket connection to establish and Uvicorn to warm up singletons
    await asyncio.sleep(3)
    
    url = "http://localhost:8000/api/v1/learner/emp_001/chat"
    # Testing query suggested for study plan routing
    payload = {"user_query": "Give me a study plan for AZ-204"}
    headers = {"Content-Type": "application/json"}
    
    print(f"\nSending POST request to {url}...")
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        
    print(f"\nHTTP Response Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Agent           : {data.get('agent')}")
        print(f"Confidence      : {data.get('confidence')}")
        print(f"Reasoning Steps : {len(data.get('reasoning_trace', []))}")
        print(f"Result Summary  : {data.get('result', {}).get('summary') if isinstance(data.get('result'), dict) else str(data.get('result'))[:200]}")
    else:
        print(f"Error Response  : {response.text}")

async def main():
    # Start the WS listener in the background
    listener_task = asyncio.create_task(listen_ws())
    
    # Send the chat request
    await send_chat()
    
    # Wait another second to ensure all trailing WS events are received
    await asyncio.sleep(2)
    
    # Cancel the listener
    listener_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
