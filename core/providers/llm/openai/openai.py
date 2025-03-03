from config.logger import setup_logging
import openai
import httpx
from core.providers.llm.base import LLMProviderBase

TAG = __name__
logger = setup_logging()


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.model_name = config.get("model_name")
        self.api_key = config.get("api_key")
        if 'base_url' in config:
            self.base_url = config.get("base_url")
        else:
            self.base_url = config.get("url")
        if "你" in self.api_key:
            logger.bind(tag=TAG).error("你还没配置LLM的密钥，请在配置文件中配置密钥，否则无法正常工作")
        
        if 'proxy_url' in config:
            self.proxy_url = config.get("proxy_url")
        else:
            self.proxy_url = "http://127.0.0.1:1080"

        if "x.ai" in self.base_url or "googleapis" in self.base_url:
            self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url,
                                        http_client=httpx.Client(
                                            proxies=self.proxy_url,  # 直接传入单一代理URL也支持
                                            timeout=httpx.Timeout(10.0)  # 可选：设置超时
                                        ))
        else:
            self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

    def response(self, session_id, dialogue):
        try:
            responses = self.client.chat.completions.create(
                model=self.model_name,
                messages=dialogue,
                stream=True
            )
            
            is_active = True
            for chunk in responses:
                try:
                    # 检查是否存在有效的choice且content不为空
                    delta = chunk.choices[0].delta if getattr(chunk, 'choices', None) else None
                    content = delta.content if hasattr(delta, 'content') else ''
                except IndexError:
                    content = ''
                if content:
                    # 处理标签跨多个chunk的情况
                    if '<think>' in content:
                        is_active = False
                        content = content.split('<think>')[0]
                    if '</think>' in content:
                        is_active = True
                        content = content.split('</think>')[-1]
                    if is_active:
                        yield content

        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in response generation: {e}")
