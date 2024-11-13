import streamlit as st
import google.generativeai as genai
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import time
import os

def check_api_key():
    """
    Kiểm tra API key có tồn tại và hợp lệ không
    """
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        if not api_key:
            st.error("⚠️ GEMINI_API_KEY chưa được cấu hình!")
            st.stop()
        return api_key
    except Exception as e:
        st.error("⚠️ GEMINI_API_KEY chưa được cấu hình trong Streamlit Secrets!")
        st.stop()

def validate_url(url):
    """
    Kiểm tra URL có hợp lệ không
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

class ArticleSummarizer:
    def __init__(self):
        self.gemini_api_key = check_api_key()
        genai.configure(api_key=self.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    async def call_gemini_api(self, prompt):
        """
        Gọi Gemini API với retry và rate limit
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            if "429" in str(e):
                st.warning("Đang chờ API... Vui lòng đợi trong giây lát.")
                time.sleep(5)  # Đợi 5 giây trước khi thử lại
                raise e  # Raise lại để retry
            raise e

    async def process_content(self, content, urls):
        """
        Xử lý nội dung với Gemini
        """
        try:
            # Bước 1: Tóm tắt và tạo tiêu đề tiếng Anh
            english_prompt = f"""
            Please process this Vietnamese text:
            1. Translate to English
            2. Create a summary (500-1000 words)
            3. Generate a title that captures the main theme
            
            Format your response exactly as:
            TITLE: [your title]
            SUMMARY: [your summary]

            Text to process: {content[:15000]}  # Giới hạn độ dài input
            """
            
            english_result = await self.call_gemini_api(english_prompt)
            
            # Parse kết quả tiếng Anh
            try:
                en_title = english_result.split('TITLE:')[1].split('SUMMARY:')[0].strip()
                en_summary = english_result.split('SUMMARY:')[1].strip()
                
                word_count = len(en_summary.split())
                
                if word_count < 500:
                    expand_prompt = f"""
                    The current summary is too short ({word_count} words). 
                    Please expand this summary to be between 500-1000 words.
                    Current summary: {en_summary}
                    """
                    
                    en_summary = await self.call_gemini_api(expand_prompt)
                    word_count = len(en_summary.split())
                
            except Exception as e:
                raise Exception(f"Không thể parse kết quả tiếng Anh: {str(e)}")
            
            # Bước 2: Dịch sang tiếng Việt
            vietnamese_prompt = f"""
            Translate this English title and summary to Vietnamese.
            Format your response exactly as:
            TITLE: [Vietnamese title]
            SUMMARY: [Vietnamese summary]

            English text:
            TITLE: {en_title}
            SUMMARY: {en_summary}
            """
            
            vietnamese_result = await self.call_gemini_api(vietnamese_prompt)
            
            try:
                vi_title = vietnamese_result.split('TITLE:')[1].split('SUMMARY:')[0].strip()
                vi_summary = vietnamese_result.split('SUMMARY:')[1].strip()
                vi_word_count = len(vi_summary.split())
            except Exception as e:
                raise Exception(f"Không thể parse kết quả tiếng Việt: {str(e)}")
            
            return {
                'title': vi_title,
                'content': vi_summary,
                'english_title': en_title,
                'english_summary': en_summary,
                'word_count': word_count,
                'vi_word_count': vi_word_count,
                'original_urls': urls
            }
            
        except Exception as e:
            raise Exception(f"Lỗi xử lý Gemini: {str(e)}")

async def process_and_update_ui(summarizer, urls):
    try:
        result = await summarizer.process_urls(urls)
        return result
    except Exception as e:
        raise e

def main():
    st.set_page_config(page_title="Ứng dụng Tóm tắt Văn bản", page_icon="📝", layout="wide")
    
    st.title("📝 Ứng dụng Tóm tắt Nhiều Bài Báo")
    st.markdown("---")

    if 'summarizer' not in st.session_state:
        st.session_state.summarizer = ArticleSummarizer()

    with st.container():
        st.subheader("🔗 Nhập URL các bài báo")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            url1 = st.text_input("URL bài báo 1", key="url1")
        with col2:
            url2 = st.text_input("URL bài báo 2", key="url2")
        with col3:
            url3 = st.text_input("URL bài báo 3", key="url3")
        
        urls = [url1, url2, url3]
        
        if st.button("Tóm tắt", type="primary"):
            if not all(urls):
                st.warning("Vui lòng nhập đủ 3 URLs!")
                return
            
            invalid_urls = [url for url in urls if not validate_url(url)]
            if invalid_urls:
                st.error(f"Các URLs sau không hợp lệ: {', '.join(invalid_urls)}")
                return
            
            progress_text = "Đang xử lý..."
            progress_bar = st.progress(0, text=progress_text)
            
            try:
                result = asyncio.run(process_and_update_ui(st.session_state.summarizer, urls))
                
                if result:
                    progress_bar.progress(100, text="Hoàn thành!")
                    st.success(f"✅ Tóm tắt thành công! (Độ dài: {result['vi_word_count']} từ tiếng Việt, {result['word_count']} từ tiếng Anh)")
                    
                    st.markdown(f"## 📌 {result['title']}")
                    st.markdown("### 📄 Bản tóm tắt")
                    st.write(result['content'])
                    
                    with st.expander("Xem phiên bản tiếng Anh"):
                        st.markdown(f"### {result['english_title']}")
                        st.write(result['english_summary'])
                    
                    with st.expander("Xem URLs gốc"):
                        for i, url in enumerate(result['original_urls'], 1):
                            st.markdown(f"Bài {i}: [{url}]({url})")
                            
            except Exception as e:
                st.error(f"Có lỗi xảy ra: {str(e)}")
            finally:
                progress_bar.empty()

if __name__ == "__main__":
    main()
