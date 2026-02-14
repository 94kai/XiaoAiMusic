MUSIC_CONFIG = {
    # 支持配置多个目录，递归扫描并建立内存索引
    "music_dirs": [
        "/Users/xuekai/Downloads/t",
        "/Users/xuekai/Downloads/test",
    ],
    # 支持索引的音频后缀（小写，带点）
    "supported_audio_extensions": [
        ".mp3",
        ".flac",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
    ],
    "search": {
        # 返回结果上限（先全匹配，再截取前 N 首）
        "max_results": 20,
        # 曲库索引定时刷新间隔（秒）；设置为 0 表示禁用定时刷新
        "refresh_interval_sec": 0,
        # 索引文件保存路径（包含歌曲路径、歌名、歌手、专辑）
        "index_file": ".cache/music_index.json",
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
            "关机"
        ],
        # 触发曲库刷新的命令词（全量匹配，忽略空格）
        "refresh_keywords": [
            "刷新曲库",
        ],
        # 触发随机播放的命令词（全量匹配，忽略空格）
        "random_play_keywords": [
            "随便听听",
        ],
    },
    "http": {
        "port": 18080,
        # 小爱可访问到的服务地址
        "base_url": "http://192.168.11.18:18080",
    },
    "logging": {
        "level": "INFO",
    },
}
