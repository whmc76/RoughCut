**文档同步版本：** RoughCut v0.1.5（2026-04-27）

RoughCut 全套自动重建服务（Windows / PowerShell）

## 一键启动（推荐）

### 1) 全套（runtime + automation）自动重建

```bash
npm run docker:auto:auto-up
```

或

```bash
pnpm run docker:auto:auto-up
```

含义：

- 启动 full 模式（runtime + automation）
- 启动 host 端文件监听
- 源码变更后自动触发 `docker compose up -d --build --force-recreate --remove-orphans`

### 2) 仅 runtime 自动重建

```bash
npm run docker:runtime:auto-up
```

或

```bash
pnpm run docker:runtime:auto-up
```

### 3) 旧版 BAT 快捷方式（等价）

- `start_roughcut.bat full-auto-watch`
- `start_roughcut.bat runtime-auto-watch`

## 入口说明

你当前服务默认使用稀有端口：

- `http://127.0.0.1:38471/`

如果端口被占用，启动脚本会按优先列表自动往后尝试（38472、38473 ...）。

## 停止

```bash
pnpm run docker:full-down
```

或

```bash
pnpm run docker:runtime:down
```

## 故障恢复建议（常用）

- 如果报 `frontend not built`，先执行一次：
  - `cd frontend`
  - `npm install`
  - `npm run build`
- 再回到项目根执行：
  - `pnpm run docker:runtime:auto-up` 或 `pnpm run docker:auto:auto-up`

## 说明

这套命令实现的是“全套自动重建”能力，适合开发时持续改动 `src/`、`frontend/` 时自动热更新到容器。 
