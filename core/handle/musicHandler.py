from config.logger import setup_logging
import os
import random
import difflib
import re
import traceback
from fuzzywuzzy import fuzz
from core.handle.sendAudioHandle import sendAudioMessage, send_stt_message

TAG = __name__
logger = setup_logging()


def _extract_song_name(text):
    """从用户输入中提取歌名（优化版）"""
    # 按关键词长度降序排列，优先匹配长关键词
    for keyword in sorted(["播放", "听", "放", "唱"], key=len, reverse=True):
        if keyword in text:
            # 使用maxsplit=1确保只分割一次
            parts = text.split(keyword, 1)
            if len(parts) > 1:
                candidate = parts[1].strip()
                
                # 清洗步骤
                candidate = _clean_song_name(candidate)
                
                if candidate:
                    return candidate
    return None

def _clean_song_name(name):
    """清洗歌名中的干扰词和符号"""
    # 去除开头修饰词（可扩展列表）
    stop_words = ["一首", "个", "的歌曲", "的歌", "音乐"]
    for word in stop_words:
        if name.startswith(word):
            name = name[len(word):].strip()
    
    # 去除包裹符号（可扩展）
    wrappers = ["《", "》", "'", "\""]
    for symbol in wrappers:
        name = name.strip(symbol)
    
    # 处理特殊符号后的内容（如冒号）
    if "：" in name or ":" in name:
        name = re.split(r"[：:]", name, 1)[-1].strip()
    
    return name

def _find_best_match(potential_song, music_files):
    """查找最匹配的歌曲（增强版）"""
    
    # 预处理目标歌名
    cleaned_target = _clean_for_matching(potential_song)
    
    # 预处理音乐库（缓存优化）
    preprocessed_files = []
    for file in music_files:
        name = os.path.splitext(file)[0]
        preprocessed_files.append((
            _clean_for_matching(name),  # 清洗后的歌名
            file  # 原始文件名
        ))
    
    best_match = None
    highest_score = 0
    
    # 多策略匹配
    for clean_name, original_file in preprocessed_files:
        # 策略1：基础相似度
        base_ratio = fuzz.ratio(cleaned_target, clean_name)
        
        # 策略2：部分匹配（适合长歌名）
        partial_ratio = fuzz.partial_ratio(cleaned_target, clean_name)
        
        # 策略3：词序无关匹配
        token_ratio = fuzz.token_sort_ratio(cleaned_target, clean_name)
        
        # 综合得分（可调整权重）
        combined_score = max(base_ratio, partial_ratio, token_ratio)
        
        # 动态阈值逻辑
        min_threshold = 60 if len(cleaned_target) > 3 else 50
        if combined_score > highest_score and combined_score >= min_threshold:
            highest_score = combined_score
            best_match = original_file
    
    return best_match if highest_score >= 50 else None

def _clean_for_matching(self, text):
    """统一匹配清洗标准"""
    # 转换为小写
    text = text.lower()
    # 移除符号
    text = re.sub(r'''[《》\"'()
$$

$$
\-—·]''', "", text)
    # 去除常见干扰词
    stop_words = ["的", "之", "与", "和", "feat", "version"]
    for word in stop_words:
        text = text.replace(word, "")
    return text.strip()


class MusicHandler:
    def __init__(self, config):
        self.config = config
        self.music_related_keywords = []

        if "music" in self.config:
            self.music_config = self.config["music"]
            self.music_dir = os.path.abspath(
                self.music_config.get("music_dir", "./music")  # 默认路径修改
            )
            self.music_related_keywords = self.music_config.get("music_commands", [])
        else:
            self.music_dir = os.path.abspath("./music")
            self.music_related_keywords = ["来一首歌", "唱一首歌", "播放音乐", "来点音乐", "背景音乐", "放首歌",
                                           "播放歌曲", "来点背景音乐", "我想听歌", "我要听歌", "放点音乐"]
        if os.path.exists(self.music_dir):
            music_txt_path = os.path.join(self.music_dir, "music.txt")
            
            # 读取已有音乐列表文件
            if os.path.exists(music_txt_path):
                try:
                    with open(music_txt_path, 'r', encoding='utf-8') as f:
                        # 按行读取并过滤空行
                        self.g_music_files = [line.strip() for line in f.read().splitlines() if line.strip()]
                        logger.bind(tag=TAG).info(f"从缓存加载{len(self.g_music_files)}个音乐文件")
                except IOError as e:
                    logger.bind(tag=TAG).error(f"读取音乐列表失败: {str(e)}")
                    self.g_music_files = []
            
            # 扫描目录并生成新列表
            else:
                # 修正1：endswith参数改为元组，并统一小写匹配
                self.g_music_files = self.get_relative_music_files(self.music_dir) 
                
                if self.g_music_files:
                    try:
                        # 修正2：每行写入一个文件名
                        with open(music_txt_path, 'w', encoding='utf-8') as f:
                            f.write('\n'.join(self.g_music_files))
                        logger.bind(tag=TAG).info(f"从目录加载{len(self.g_music_files)}个音乐文件")
                        logger.bind(tag=TAG).debug(f"已生成音乐列表: {self.g_music_files}")
                    except IOError as e:
                        logger.bind(tag=TAG).error(f"写入音乐列表失败: {str(e)}")
                else:
                    logger.bind(tag=TAG).warning("目录中未找到 .mp3 或 .wav 文件")

    def get_relative_music_files(self, music_dir):
        music_files = []
        for root, dirs, files in os.walk(music_dir):
            for file in files:
                if file.lower().endswith(('.mp3', '.wav')):
                    # 生成相对路径（关键步骤）
                    rel_path = os.path.relpath(os.path.join(root, file), music_dir)
                    music_files.append(rel_path)
        return music_files

    async def handle_music_command(self, conn, text):
        """处理音乐播放指令"""
        clean_text = re.sub(r'[^\w\s]', '', text).strip()
        logger.bind(tag=TAG).debug(f"检查是否是音乐命令: {clean_text}")

        # 尝试匹配具体歌名
        if os.path.exists(self.music_dir):
            # music_files = [f for f in os.listdir(self.music_dir) if f.endswith('.mp3')]
            # logger.bind(tag=TAG).debug(f"找到的音乐文件: {music_files}")

            potential_song = _extract_song_name(clean_text)
            if potential_song:
                best_match = _find_best_match(potential_song, self.g_music_files)
                if best_match:
                    logger.bind(tag=TAG).info(f"找到最匹配的歌曲: {best_match}")
                    await self.play_local_music(conn, specific_file=best_match)
                    return True

        # 检查是否是通用播放音乐命令
        if any(cmd in clean_text for cmd in self.music_related_keywords):
            await self.play_local_music(conn)
            return True

        return False

    async def play_local_music(self, conn, specific_file=None):
        """播放本地音乐文件"""
        try:
            if not os.path.exists(self.music_dir):
                logger.bind(tag=TAG).error(f"音乐目录不存在: {self.music_dir}")
                return

            # 确保路径正确性
            if specific_file:
                music_path = os.path.join(self.music_dir, specific_file)
                if not os.path.exists(music_path):
                    logger.bind(tag=TAG).error(f"指定的音乐文件不存在: {music_path}")
                    return
                selected_music = specific_file
            else:
                # music_files = [f for f in os.listdir(self.music_dir) if f.endswith('.mp3')]
                if not self.g_music_files:
                    logger.bind(tag=TAG).error("未找到MP3音乐文件")
                    return
                selected_music = random.choice(self.g_music_files)
                music_path = os.path.join(self.music_dir, selected_music)
            text = f"正在播放{selected_music}"
            await send_stt_message(conn, text)
            conn.tts_first_text = selected_music
            conn.tts_last_text = selected_music
            conn.llm_finish_task = True
            opus_packets, duration = conn.tts.wav_to_opus_data(music_path)
            await sendAudioMessage(conn, opus_packets, duration, selected_music)

        except Exception as e:
            logger.bind(tag=TAG).error(f"播放音乐失败: {str(e)}")
            logger.bind(tag=TAG).error(f"详细错误: {traceback.format_exc()}")
