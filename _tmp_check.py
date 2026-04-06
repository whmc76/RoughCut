from pathlib import Path
import os
configured = os.getenv('ROUGHCUT_FRONTEND_DIST')
candidates=[]
if configured:
    candidates.append(Path(configured).expanduser())
module_path = Path('/app/src/roughcut/main.py').resolve()
candidates.extend(parent / 'frontend' / 'dist' for parent in module_path.parents)
candidates.append(Path.cwd()/ 'frontend' / 'dist')
seen=set()
for candidate in candidates:
    resolved=candidate.resolve()
    if resolved in seen:
        continue
    seen.add(resolved)
    print(str(resolved), 'index?', (resolved/'index.html').exists(), 'assets?', (resolved/'assets').exists())
