import asyncio
import os

from dotenv import load_dotenv

from neiltool.database import Database

load_dotenv()

database = Database(os.environ["DATABASE_URL"])


async def main():
    await database.metadata_create_all()


asyncio.run(main())
