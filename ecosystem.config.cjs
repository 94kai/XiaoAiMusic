module.exports = {
  apps: [
    {
      name: "XiaoAiMusic",
      cwd: __dirname,
      script: "uv",
      args: "run main.py",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      out_file: "logs/pm2-out.log",
      error_file: "logs/pm2-err.log",
      merge_logs: true,
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
