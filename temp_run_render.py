import asyncio
import traceback
from roughcut.pipeline.steps import run_render

job_id = "653995ce-3399-4f22-ad57-a46259f1b814"

async def main():
    try:
        await run_render(job_id)
        print("run_render ok")
    except Exception as exc:
        traceback.print_exc()

asyncio.run(main())
