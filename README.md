# XiaoAi Music

监听小爱识别文本，搜索本地曲库并控制播放。

## 致谢

感谢 [idootop/open-xiaoai](https://github.com/idootop/open-xiaoai) 项目。

## 功能
<img width="1229" height="481" alt="image" src="https://github.com/user-attachments/assets/9facf069-0901-4037-9364-54159d25a0ba" />

- 启动时建立本地曲库内存索引，并按配置定时刷新
- 识别到播放关键词（默认“播放xxx”）：在内存索引中做子串搜索并播放
- 识别到停止关键词（默认“停止播放/暂停播放/停止/暂停”等）：暂停当前播放

## 运行

使用本项目前，请先根据 [idootop/open-xiaoai](https://github.com/idootop/open-xiaoai) 完成小爱音箱刷机并安装 client。

随后确保小爱端 client 已运行并连接到本机 `4399` 端口。

```bash
uv run main.py
```

运行前请先编辑 `config.py`：

- `music_dirs`：配置多个本地音乐目录
- `search.max_results`：播放队列取前 N 首
- `search.refresh_interval_sec`：曲库索引刷新间隔（秒）
- `commands.play_keywords` / `commands.stop_keywords`：语音命令关键词
- `http.device_ip`：填写小爱设备可访问到的本机 IP（会自动拼接端口）

## TODO
- [ ] 随便听听（随机播放N首）
- [ ] 搜索结果乱序播放
- [ ] 优化搜索逻辑
  - [ ] 模糊匹配
  - [ ] 速度优化
- [ ] ... ...

