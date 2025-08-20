#!/usr/bin/with-contenv bashio

# 获取配置选项
MUSIC_DIR=$(bashio::config 'music_directory')
PORT=$(bashio::config 'port')
TITLE=$(bashio::config 'title')

# 输出启动信息
bashio::log.info "启动本地音乐播放器..."
bashio::log.info "音乐目录: ${MUSIC_DIR}"
bashio::log.info "端口: ${PORT}"
bashio::log.info "标题: ${TITLE}"

# 设置环境变量
export MUSIC_DIRECTORY="${MUSIC_DIR}"
export SERVER_PORT="${PORT}"
export APP_TITLE="${TITLE}"

# 启动应用
python music_server.py