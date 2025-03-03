#!/usr/bin/env rye run python
import os
import asyncio
import time
import uuid
import base64    
import re
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI
from loguru import logger
from core.providers.tts.base import TTSProviderBase

TAG = __name__

class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)

        self.response_format = config.get("response_format")
        self.voice = {}
        self.voice["cn"] = config.get("voice_zh")
        self.voice["en"] = config.get("voice_en")
        self.api_url = config.get("url")

    def generate_filename(self, extension=".wav"):
        return os.path.join(self.output_file, f"tts-{datetime.now().date()}@{uuid.uuid4().hex}{extension}")

    def split_chinese_english(self, text):
        # 改进后的正则表达式
        pattern = re.compile(
            r'''
            ( [\u4e00-\u9fa5]+[，。！？、,.!?]*[\u4e00-\u9fa5]* )  # 中文部分（允许含中英文标点）
            | ( [a-zA-Z0-9\s',.!?\-]+ )                          # 英文部分（仅保留纯英文标点）
            ''', re.X
        )
        
        segments = []
        for match in pattern.finditer(text):
            chn_part, eng_part = match.groups()
            if chn_part and chn_part.strip():
                # 清理纯标点片段（如连续的英文标点）
                if re.match(r'^[,.!?]+$', chn_part):
                    segments.append(["cn", chn_part.strip()])
                else:
                    segments.append(["cn", chn_part.strip()])
            elif eng_part and eng_part.strip():
                segments.append(["en", eng_part.strip()])
        
        # 合并相邻的中文标点（如中英文标点混合）
        merged = []
        for s in segments:
            if merged and merged[-1][0] == "cn" and s[0] == "cn":
                merged[-1] = ["cn", merged[-1][1] + s[1]]
            else:
                merged.append(s)
        
        return merged

    def split_mixed_sentence(sentence):
        """
        将中英文混合的句子拆分成单独的中文和英文部分，保持中文句子完整
        
        参数:
        sentence - 输入的混合句子
        
        返回:
        list - 分割后的句子列表，每个元素为 [语言, 字符串]，语言为 "en" 或 "cn"
        """
        # 定义中文字符的Unicode范围（包含中文标点）
        chinese_pattern = re.compile(r'[\u4e00-\u9fff，。！？、；：,\.\?:;\!]+')
        # 定义英文字符和常见标点（排除被中文使用的标点）
        english_pattern = re.compile(r'[a-zA-Z\s\']+')  # 去掉 ,.?:;! 只保留空格和单引号
        
        # 存储结果
        result = []
        
        # 当前处理的字符串
        remaining = sentence.strip()
        
        while remaining:
            # 先尝试匹配中文
            chinese_match = chinese_pattern.match(remaining)
            if chinese_match:
                chinese_part = chinese_match.group()
                # 扩展中文部分，直到遇到英文或字符串结束
                pos = chinese_match.end()
                while pos < len(remaining) and not english_pattern.match(remaining[pos:]):
                    next_chinese = chinese_pattern.match(remaining[pos:])
                    if next_chinese:
                        chinese_part += next_chinese.group()
                        pos += next_chinese.end()
                    else:
                        # 如果不是英文也不是中文，添加单个字符
                        chinese_part += remaining[pos]
                        pos += 1
                result.append(["cn", chinese_part])
                remaining = remaining[len(chinese_part):].strip()
                continue
            
            # 再尝试匹配英文
            english_match = english_pattern.match(remaining)
            if english_match:
                english_part = english_match.group()
                result.append(["en", english_part.strip()])
                remaining = remaining[len(english_part):].strip()
                continue
            
            # 如果开头既不是中文也不是英文，跳过非匹配字符
            if remaining:
                remaining = remaining[1:].strip()
        
        # 过滤空字符串并返回
        return [item for item in result if item[1]]

    async def text_to_speak(self, text, output_file):
        speech_file_path = output_file
        openai = AsyncOpenAI(base_url=self.api_url, api_key="not-needed-for-local")
        
        try:
            # try:
            #     lang = detect(text)
            #     voice_auto =  self.voice_zh if lang.startswith('zh') else self.voice_en if lang == 'en' else self.voice_zh
            # except:
            #     voice_auto = self.voice_zh  # 处理空字符串或无法检测的情况

            
            try:
                # splitStr = self.split_mixed_sentence(text)
                splitStr = self.split_chinese_english(text)
            except:
                splitStr = [["cn", text]]

            logger.bind(tag=TAG).info(f"kokoro voice:[{text.strip()}]-{str(splitStr)}")
            start_time_all = time.time()
            for one in splitStr:
                if len(one[1].strip()) == 0:
                    break
                start_time = time.time()
                # Use streaming endpoint with mp3 format
                async with openai.audio.speech.with_streaming_response.create(
                    model="kokoro",
                    voice= self.voice[one[0]],
                    input= one[1],
                    response_format=self.response_format
                ) as response:
                    print(f"File - Time to first byte: {int((time.time() - start_time) * 1000)}ms")
                    
                    # Open file in binary write mode
                    with open(speech_file_path, 'ab') as f:
                        async for chunk in response.iter_bytes():
                            f.write(chunk)
                    
            print(f"File  completed in {int((time.time() - start_time_all) * 1000)}ms")
        except Exception as e:
            print(f"Error processing file : {e}")
