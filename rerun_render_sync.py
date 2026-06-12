import asyncio, traceback
from roughcut.pipeline.steps import run_step_sync

try:
    run_step_sync('render', '653995ce-3399-4f22-ad57-a46259f1b814')
    print('ok')
except Exception as exc:
    print('ERR', type(exc).__name__, str(exc))
    traceback.print_exc()
