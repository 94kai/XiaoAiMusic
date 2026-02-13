MUSIC_CONFIG = {
    # 支持配置多个目录，递归扫描并建立内存索引
    "music_dirs": [
        "/Users/xuekai/Downloads/t",
        "/Users/xuekai/Downloads/test",
    ],
    "search": {
        # 返回结果上限（先全匹配，再截取前 N 首）
        "max_results": 10,
        # 曲库索引定时刷新间隔（秒）
        "refresh_interval_sec": 300,
    },
    "commands": {
        # 触发播放命令的前缀
        "play_keywords": ["播放"],
        # 触发停止播放的命令词（会去掉空格后精确匹配）
        "stop_keywords": [
            "停止播放",
            "暂停播放",
            "停止",
            "暂停",
            "闭嘴",
            "别放了",
            "不要放了",
        ],
    },
    "http": {
        # 本地 HTTP 服务监听地址
        "host": "0.0.0.0",
        "port": 18080,
        # 小爱设备可访问到的本机 IP（自动拼成 http://<ip>:<port>）
        "device_ip": "192.168.11.18",
    },
    "logging": {
        "level": "INFO",
    },
}
