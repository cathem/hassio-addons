#!/usr/bin/env python3
"""
本地音乐播放器服务器
支持扫描本地音乐文件并提供Web播放界面
"""

import os
import json
import logging
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

from flask import Flask, jsonify, request, send_file, render_template_string
from flask_cors import CORS
import mutagen
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from werkzeug.serving import WSGIRequestHandler

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# 配置
MUSIC_DIR = os.environ.get('MUSIC_DIRECTORY', '/media/music')
PORT = int(os.environ.get('SERVER_PORT', 8080))
APP_TITLE = os.environ.get('APP_TITLE', '本地音乐播放器')

# 全局变量
music_library = []

class MusicScanner:
    """音乐文件扫描器"""
    
    SUPPORTED_FORMATS = {'.mp3', '.mp4', '.m4a', '.flac', '.ogg', '.wav'}
    
    @classmethod
    def scan_directory(cls, directory: str) -> List[Dict]:
        """扫描目录中的音乐文件"""
        tracks = []
        music_path = Path(directory)
        
        if not music_path.exists():
            logger.warning(f"音乐目录不存在: {directory}")
            return tracks
        
        logger.info(f"开始扫描音乐目录: {directory}")
        
        for file_path in music_path.rglob('*'):
            if file_path.suffix.lower() in cls.SUPPORTED_FORMATS:
                try:
                    track_info = cls._extract_track_info(file_path)
                    if track_info:
                        tracks.append(track_info)
                except Exception as e:
                    logger.warning(f"读取文件失败 {file_path}: {e}")
        
        logger.info(f"扫描完成，找到 {len(tracks)} 个音频文件")
        return tracks
    
    @classmethod
    def _extract_track_info(cls, file_path: Path) -> Optional[Dict]:
        """提取音频文件信息"""
        try:
            # 生成唯一ID
            file_id = hashlib.md5(str(file_path).encode()).hexdigest()
            
            # 读取音频文件
            audio_file = mutagen.File(file_path)
            
            # 默认信息
            title = file_path.stem
            artist = "Unknown Artist"
            album = "Unknown Album"
            duration = 0
            
            if audio_file is not None:
                # 提取元数据
                if hasattr(audio_file, 'info') and audio_file.info:
                    duration = getattr(audio_file.info, 'length', 0)
                
                # 根据文件类型提取标签
                if isinstance(audio_file, MP3):
                    title = cls._get_id3_tag(audio_file, 'TIT2') or title
                    artist = cls._get_id3_tag(audio_file, 'TPE1') or artist
                    album = cls._get_id3_tag(audio_file, 'TALB') or album
                elif isinstance(audio_file, (MP4)):
                    title = cls._get_mp4_tag(audio_file, '\xa9nam') or title
                    artist = cls._get_mp4_tag(audio_file, '\xa9ART') or artist
                    album = cls._get_mp4_tag(audio_file, '\xa9alb') or album
                elif isinstance(audio_file, FLAC):
                    title = cls._get_vorbis_tag(audio_file, 'TITLE') or title
                    artist = cls._get_vorbis_tag(audio_file, 'ARTIST') or artist
                    album = cls._get_vorbis_tag(audio_file, 'ALBUM') or album
                else:
                    # 通用标签提取
                    tags = audio_file.tags or {}
                    for key, value in tags.items():
                        key_lower = key.lower()
                        if 'title' in key_lower:
                            title = str(value[0] if isinstance(value, list) else value)
                        elif 'artist' in key_lower:
                            artist = str(value[0] if isinstance(value, list) else value)
                        elif 'album' in key_lower:
                            album = str(value[0] if isinstance(value, list) else value)
            
            return {
                'id': file_id,
                'title': str(title),
                'artist': str(artist),
                'album': str(album),
                'filename': file_path.name,
                'path': str(file_path),
                'relative_path': str(file_path.relative_to(MUSIC_DIR)),
                'duration': round(duration, 2),
                'size': file_path.stat().st_size,
                'format': file_path.suffix.lower()[1:]
            }
            
        except Exception as e:
            logger.error(f"提取音频信息失败 {file_path}: {e}")
            return None
    
    @staticmethod
    def _get_id3_tag(audio_file, tag_name):
        """获取ID3标签"""
        if audio_file.tags and tag_name in audio_file.tags:
            value = audio_file.tags[tag_name]
            return str(value[0]) if isinstance(value, list) and value else str(value)
        return None
    
    @staticmethod
    def _get_mp4_tag(audio_file, tag_name):
        """获取MP4标签"""
        if audio_file.tags and tag_name in audio_file.tags:
            value = audio_file.tags[tag_name]
            return str(value[0]) if isinstance(value, list) and value else str(value)
        return None
    
    @staticmethod
    def _get_vorbis_tag(audio_file, tag_name):
        """获取Vorbis标签(FLAC, OGG)"""
        if audio_file.tags and tag_name.upper() in audio_file.tags:
            value = audio_file.tags[tag_name.upper()]
            return str(value[0]) if isinstance(value, list) and value else str(value)
        return None


@app.route('/')
def index():
    """主页面"""
    return render_template_string(HTML_TEMPLATE, title=APP_TITLE)

@app.route('/api/library')
def get_library():
    """获取音乐库"""
    return jsonify({
        'tracks': music_library,
        'total': len(music_library)
    })

@app.route('/api/scan')
def scan_library():
    """重新扫描音乐库"""
    global music_library
    music_library = MusicScanner.scan_directory(MUSIC_DIR)
    return jsonify({
        'message': f'扫描完成，找到 {len(music_library)} 个文件',
        'total': len(music_library)
    })

@app.route('/api/stream/<track_id>')
def stream_track(track_id):
    """流式传输音频文件"""
    track = next((t for t in music_library if t['id'] == track_id), None)
    if not track:
        return jsonify({'error': '文件不存在'}), 404
    
    file_path = Path(track['path'])
    if not file_path.exists():
        return jsonify({'error': '文件已被删除'}), 404
    
    # 设置MIME类型
    mimetype, _ = mimetypes.guess_type(str(file_path))
    if not mimetype:
        mimetype = 'audio/mpeg'  # 默认
    
    return send_file(
        str(file_path),
        mimetype=mimetype,
        as_attachment=False,
        conditional=True
    )

@app.route('/api/search')
def search_tracks():
    """搜索音轨"""
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify({'tracks': music_library})
    
    filtered_tracks = [
        track for track in music_library
        if query in track['title'].lower() or
           query in track['artist'].lower() or
           query in track['album'].lower()
    ]
    
    return jsonify({'tracks': filtered_tracks})


# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#1a1a1a">
    <link rel="manifest" href="data:application/manifest+json,{'name':'{{ title }}','start_url':'/','display':'standalone','theme_color':'%231a1a1a'}">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            color: #ffffff;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding: 20px 0;
        }
        
        .header h1 {
            font-size: 2.5rem;
            background: linear-gradient(45deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 10px;
        }
        
        .stats {
            color: #aaa;
            font-size: 0.9rem;
        }
        
        .player-section {
            background: rgba(45, 45, 45, 0.8);
            backdrop-filter: blur(10px);
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 25px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        
        .current-track {
            text-align: center;
            margin-bottom: 20px;
        }
        
        .track-title {
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 5px;
        }
        
        .track-artist {
            color: #aaa;
            font-size: 1rem;
        }
        
        audio {
            width: 100%;
            margin: 20px 0;
            border-radius: 10px;
        }
        
        .controls {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin: 20px 0;
            flex-wrap: wrap;
        }
        
        .btn {
            background: linear-gradient(45deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }
        
        .btn:active {
            transform: translateY(0);
        }
        
        .btn.secondary {
            background: linear-gradient(45deg, #36d1dc 0%, #5b86e5 100%);
            box-shadow: 0 4px 15px rgba(54, 209, 220, 0.3);
        }
        
        .volume-section {
            display: flex;
            align-items: center;
            gap: 15px;
            margin: 20px 0;
        }
        
        .volume-slider {
            flex: 1;
            height: 6px;
            background: #444;
            border-radius: 3px;
            outline: none;
            -webkit-appearance: none;
        }
        
        .volume-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 18px;
            height: 18px;
            background: linear-gradient(45deg, #667eea 0%, #764ba2 100%);
            border-radius: 50%;
            cursor: pointer;
        }
        
        .search-section {
            margin-bottom: 25px;
        }
        
        .search-input {
            width: 100%;
            padding: 15px 20px;
            border: none;
            border-radius: 25px;
            background: rgba(45, 45, 45, 0.8);
            color: #fff;
            font-size: 1rem;
            backdrop-filter: blur(10px);
            transition: all 0.3s ease;
        }
        
        .search-input:focus {
            outline: none;
            background: rgba(45, 45, 45, 0.9);
            box-shadow: 0 0 20px rgba(102, 126, 234, 0.3);
        }
        
        .search-input::placeholder {
            color: #aaa;
        }
        
        .track-list {
            background: rgba(45, 45, 45, 0.8);
            border-radius: 15px;
            padding: 20px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        
        .track-item {
            padding: 15px;
            border-bottom: 1px solid rgba(68, 68, 68, 0.5);
            cursor: pointer;
            transition: all 0.3s ease;
            border-radius: 8px;
            margin-bottom: 5px;
        }
        
        .track-item:hover {
            background: rgba(102, 126, 234, 0.1);
            transform: translateX(5px);
        }
        
        .track-item:last-child {
            border-bottom: none;
            margin-bottom: 0;
        }
        
        .track-item.playing {
            background: rgba(102, 126, 234, 0.2);
            border-left: 4px solid #667eea;
        }
        
        .track-name {
            font-weight: 600;
            margin-bottom: 5px;
            font-size: 1rem;
        }
        
        .track-info {
            color: #aaa;
            font-size: 0.85rem;
        }
        
        .duration {
            color: #888;
            font-size: 0.8rem;
            margin-top: 3px;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #aaa;
        }
        
        .spinner {
            border: 3px solid rgba(102, 126, 234, 0.3);
            border-radius: 50%;
            border-top: 3px solid #667eea;
            width: 30px;
            height: 30px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #aaa;
        }
        
        .empty-state h3 {
            margin-bottom: 10px;
            color: #ccc;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 15px;
            }
            
            .header h1 {
                font-size: 2rem;
            }
            
            .controls {
                gap: 10px;
            }
            
            .btn {
                padding: 10px 20px;
                font-size: 0.8rem;
            }
        }
        
        /* 波浪动画 */
        .wave {
            display: inline-block;
            margin-left: 10px;
        }
        
        .wave span {
            display: inline-block;
            width: 4px;
            height: 20px;
            background: #667eea;
            margin: 0 1px;
            border-radius: 2px;
            animation: wave 1.5s ease-in-out infinite;
        }
        
        .wave span:nth-child(2) { animation-delay: 0.1s; }
        .wave span:nth-child(3) { animation-delay: 0.2s; }
        .wave span:nth-child(4) { animation-delay: 0.3s; }
        
        @keyframes wave {
            0%, 40%, 100% { transform: scaleY(0.4); }
            20% { transform: scaleY(1); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎵 {{ title }}</h1>
            <div class="stats" id="stats">正在加载音乐库...</div>
        </div>
        
        <div class="player-section">
            <div class="current-track">
                <div class="track-title" id="currentTitle">选择一首歌曲开始播放</div>
                <div class="track-artist" id="currentArtist"></div>
            </div>
            
            <audio id="audioPlayer" controls preload="metadata">
                您的浏览器不支持音频播放
            </audio>
            
            <div class="controls">
                <button class="btn" onclick="previousTrack()">⏮️ 上一曲</button>
                <button class="btn" onclick="togglePlayPause()" id="playBtn">▶️ 播放</button>
                <button class="btn" onclick="nextTrack()">⏭️ 下一曲</button>
                <button class="btn secondary" onclick="shufflePlay()">🔀 随机</button>
                <button class="btn secondary" onclick="rescanLibrary()">🔄 刷新</button>
            </div>
            
            <div class="volume-section">
                <span>🔊</span>
                <input type="range" class="volume-slider" id="volumeSlider" 
                       min="0" max="100" value="80" oninput="setVolume()">
                <span id="volumeValue">80%</span>
            </div>
        </div>
        
        <div class="search-section">
            <input type="text" class="search-input" placeholder="🔍 搜索歌曲、艺术家或专辑..." 
                   oninput="searchTracks()" id="searchInput">
        </div>
        
        <div class="track-list">
            <div id="trackList" class="loading">
                <div class="spinner"></div>
                正在加载音乐库...
            </div>
        </div>
    </div>

    <script>
        let tracks = [];
        let filteredTracks = [];
        let currentTrackIndex = -1;
        let isPlaying = false;
        let audioPlayer = document.getElementById('audioPlayer');
        
        // 格式化时间
        function formatTime(seconds) {
            if (!seconds || seconds === 0) return '0:00';
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins}:${secs.toString().padStart(2, '0')}`;
        }
        
        // 格式化文件大小
        function formatSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
        
        // 加载音乐库
        async function loadLibrary() {
            try {
                const response = await fetch('/api/library');
                const data = await response.json();
                tracks = data.tracks;
                filteredTracks = [...tracks];
                displayTracks(filteredTracks);
                updateStats(data.total);
            } catch (error) {
                console.error('加载音乐库失败:', error);
                document.getElementById('trackList').innerHTML = `
                    <div class="empty-state">
                        <h3>加载失败</h3>
                        <p>无法连接到服务器</p>
                        <button class="btn" onclick="loadLibrary()">重试</button>
                    </div>
                `;
            }
        }
        
        // 重新扫描音乐库
        async function rescanLibrary() {
            document.getElementById('trackList').innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    正在重新扫描音乐库...
                </div>
            `;
            
            try {
                await fetch('/api/scan');
                await loadLibrary();
            } catch (error) {
                console.error('重新扫描失败:', error);
            }
        }
        
        // 更新统计信息
        function updateStats(total) {
            document.getElementById('stats').textContent = `共找到 ${total} 首歌曲`;
        }
        
        // 显示音轨列表
        function displayTracks(tracksToShow) {
            const trackList = document.getElementById('trackList');
            
            if (tracksToShow.length === 0) {
                trackList.innerHTML = `
                    <div class="empty-state">
                        <h3>没有找到音乐文件</h3>
                        <p>请检查音乐目录或尝试重新扫描</p>
                        <button class="btn" onclick="rescanLibrary()">重新扫描</button>
                    </div>
                `;
                return;
            }
            
            trackList.innerHTML = tracksToShow.map((track, index) => `
                <div class="track-item ${currentTrackIndex === tracks.indexOf(track) ? 'playing' : ''}" 
                     onclick="playTrack('${track.id}')">
                    <div class="track-name">
                        ${track.title}
                        ${currentTrackIndex === tracks.indexOf(track) && isPlaying ? 
                            '<span class="wave"><span></span><span></span><span></span><span></span></span>' : ''}
                    </div>
                    <div class="track-info">
                        <span>${track.artist}</span> • <span>${track.album}</span>
                    </div>
                    <div class="duration">
                        ${formatTime(track.duration)} • ${track.format.toUpperCase()} • ${formatSize(track.size)}
                    </div>
                </div>
            `).join('');
        }
        
        // 播放指定音轨
        async function playTrack(trackId) {
            const track = tracks.find(t => t.id === trackId);
            if (!track) return;
            
            currentTrackIndex = tracks.indexOf(track);
            audioPlayer.src = `/api/stream/${trackId}`;
            
            document.getElementById('currentTitle').textContent = track.title;
            document.getElementById('currentArtist').textContent = `${track.artist} - ${track.album}`;
            
            try {
                await audioPlayer.play();
                isPlaying = true;
                updatePlayButton();
                displayTracks(filteredTracks);
            } catch (error) {
                console.error('播放失败:', error);
            }
        }
        
        // 播放/暂停切换
        function togglePlayPause() {
            if (audioPlayer.src) {
                if (isPlaying) {
                    audioPlayer.pause();
                } else {
                    audioPlayer.play();
                }
            }
        }
        
        // 更新播放按钮
        function updatePlayButton() {
            const playBtn = document.getElementById('playBtn');
            playBtn.text