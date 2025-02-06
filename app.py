import logging
import asyncio
import aiohttp
import hashlib
import zlib
import streamlit as st
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from datetime import datetime, timedelta

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self, ttl: int = 3600):
        self.cache = {}
        self.ttl = ttl  # Thời gian sống của cache (1 giờ mặc định)
    
    def get(self, key: str) -> Any:
        if key in self.cache:
            timestamp, compressed_value = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return zlib.decompress(compressed_value).decode('utf-8')
            else:
                del self.cache[key]
        return None

    def set(self, key: str, value: Any):
        compressed_value = zlib.compress(value.encode('utf-8'))
        self.cache[key] = (datetime.now(), compressed_value)

class NewsArticleGenerator:
    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0"}
        self.cache = CacheManager()
    
    async def fetch_url(self, url: str) -> str:
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cached_content = self.cache.get(cache_key)
        if cached_content:
            return cached_content
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    content = await response.text()
                    self.cache.set(cache_key, content)
                    return content
        except aiohttp.ClientError as e:
            logger.error(f"Lỗi mạng khi đọc {url}: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Lỗi không xác định khi đọc {url}: {str(e)}")
            raise
    
    def extract_content(self, html: str) -> Dict[str, str]:
        try:
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.string if soup.title else "Không có tiêu đề"
            body = " ".join([p.text for p in soup.find_all('p')])
            return {"title": title, "content": body}
        except Exception as e:
            logger.error(f"Lỗi khi trích xuất nội dung: {str(e)}")
            raise

class ArticleGenerator:
    def __init__(self):
        self.cache = CacheManager()

    async def optimize_content(self, content: str) -> str:
        # Tối ưu nội dung bài viết
        optimized_content = content.replace("  ", " ").strip()
        return optimized_content

def create_ui_components():
    return {
        'url_input': st.text_input(
            label="URL bài báo",
            placeholder="https://...",
            help="Nhập URL bài báo cần tổng hợp"
        ),
        'progress_bar': st.progress(0),
        'status': st.empty()
    }

def show_article_preview(article: Dict[str, Any]):
    st.markdown(f"""
    <div class="article-preview">
        <h1>{article['title']}</h1>
        <div class="metadata">
            <span>Độ dài: {len(article['content'].split())} từ</span>
        </div>
        <div class="content">{article['content'][:500]}...</div>
    </div>
    """, unsafe_allow_html=True)

async def main():
    st.title("Tổng hợp & tối ưu hóa bài báo")
    components = create_ui_components()
    url = components['url_input']
    
    if url:
        generator = NewsArticleGenerator()
        article_gen = ArticleGenerator()
        components['status'].text("Đang tải nội dung...")
        try:
            html = await generator.fetch_url(url)
            article = generator.extract_content(html)
            optimized_content = await article_gen.optimize_content(article['content'])
            article['content'] = optimized_content
            show_article_preview(article)
            components['status'].text("Hoàn thành!")
        except Exception as e:
            components['status'].text(f"Lỗi: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
