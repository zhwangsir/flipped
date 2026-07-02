# flipped 桌面壳(Electron · M6.8)

把 Console 包成桌面 App:主进程静态服务 `console/dist` + 拉起后端(:8011,exo 直连)+ 开窗。
链路不变:Console → 后端 → OpenHands 沙盒(:8000)。

## 开发运行
```bash
cd desktop && npm install          # 装 electron(China 走 npmmirror,见 .npmrc)
npm run dev                        # = build:console(VITE_API_BASE_URL→:8011)+ electron .
```
`npm run dev` 会先用桌面后端地址(:8011)重建 Console dist,再起窗。
前置:OpenHands 沙盒容器已起(`bash scripts/dev_up.sh` 或手动),exo 模型在线。
主进程会自动:静态服务 dist、拉起后端(:8011,若未运行)、开窗加载 Console。

> 注:后端 CORS 已放行 localhost 任意端口(M6.8),桌面壳的静态源(:5399)可直连后端。

## 打包(三平台)
```bash
npm run dist    # electron-builder → desktop/release/(mac dmg / win nsis / linux AppImage)
```
> 产品化收尾:随包内嵌 Python sidecar(python-build-standalone,D11)让终端用户免装 Python;
> 三平台签名/公证需相应证书(mac Apple Developer / win Authenticode)。Windows 包需在 Windows 构建(见 D17)。

## 环境变量
- `FLIPPED_BACKEND_PORT`(默认 8011)· `FLIPPED_STATIC_PORT`(默认 5399)
- `FLIPPED_MODEL_BASE_URL`(默认 exo 直连)· `OPENHANDS_AGENT_HOST`(默认 :8000)
- `FLIPPED_PYTHON`(默认 ../.venv/bin/python)
