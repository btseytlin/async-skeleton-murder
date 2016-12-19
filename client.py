import asyncio
import websockets
import concurrent.futures
HOST ='46.101.223.26'
PORT = 8765



async def handle_reading(websocket):
    while True:
        history = await websocket.recv()
        print(history)

async def handle_sending(websocket):
    loop = asyncio.get_event_loop()

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1,
    )

    while True:
        msg = await loop.run_in_executor(executor, input)
        await websocket.send(msg)


async def client():
    global websocket
    websocket = await websockets.connect('ws://{}:{}'.format(HOST, PORT))
    asyncio.ensure_future(handle_reading(websocket))
    asyncio.ensure_future(handle_sending(websocket))


async def cleanup():
    websocket.close()

websocket = None
loop = asyncio.get_event_loop()
loop.run_until_complete(client())
try:
    loop.run_forever()
finally:
    loop.run_until_complete(cleanup())
loop.close()