import asyncio
from crypto_history import client


async def main():
    await client.client_code()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
