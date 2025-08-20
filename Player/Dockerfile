FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    libc6-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制requirements.txt并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app/ .

# 复制启动脚本
COPY run.sh /
RUN chmod +x /run.sh

# 暴露端口
EXPOSE 8080

# 设置启动命令
CMD ["/run.sh"]