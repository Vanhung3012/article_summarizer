import streamlit as st
import google.generativeai as genai
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import time
import os
from tenacity import retry, stop_after_attempt, wait_exponential

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

    async def fetch_url(self, url):
        """
        Đọc URL bất đồng bộ sử dụng aiohttp
        """
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url) as response:
                    return await response.text()
        except Exception as e:
            raise Exception(f"Lỗi khi đọc URL {url}: {str(e)}")

    def extract_content_from_html(self, html):
        """
        Trích xuất nội dung từ HTML sử dụng BeautifulSoup
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Loại bỏ các thẻ không cần thiết
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe']):
                tag.decompose()
            
            # Lấy nội dung từ các thẻ p
            paragraphs = soup.find_all('p')
            content = ' '.join([p.get_text().strip() for p in paragraphs])
            
            return content
        except Exception as e:
            raise Exception(f"Lỗi khi parse HTML: {str(e)}")

    async def extract_content_from_url(self, url):
        """
        Trích xuất nội dung từ URL
        """
        html = await self.fetch_url(url)
        return self.extract_content_from_html(html)

    async def process_urls(self, urls):
        """
        Xử lý nhiều URLs đồng thời
        """
        try:
            start_time = time.time()
            
            # Đọc nội dung từ tất cả URLs đồng thời
            contents = await asyncio.gather(
                *[self.extract_content_from_url(url.strip()) for url in urls],
                return_exceptions=True  # Thêm để xử lý ngoại lệ
            )
            
            # Lọc ra các lỗi từ kết quả
            contents = [content for content in contents if not isinstance(content, Exception)]
            
            if not contents:
                raise Exception("Tất cả các URL đều không hợp lệ hoặc có lỗi.")
            
            # Kết hợp nội dung
            combined_content = "\n\n---\n\n".join(contents)
            
            print(f"Thời gian đọc URLs: {time.time() - start_time:.2f} giây")
            
            # Xử lý với Gemini
            result = await self.process_content(combined_content, urls)
            
            print(f"Tổng thời gian xử lý: {time.time() - start_time:.2f} giây")
            
            return result
            
        except Exception as e:
            raise Exception(f"Lỗi xử lý URLs: {str(e)}")

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
                time.sleep(5)
                raise e
            raise e

    async def process_content(self, content, urls):
        """
        Xử lý nội dung với Gemini
        """
        try:
            # Bước 1: Tóm tắt và tạo tiêu đề tiếng Anh
            english_prompt = f"""
            Create a detailed article with clear sections and paragraphs for this Vietnamese text.
            Ensure the summary is over 500 words.
            Each paragraph should be distinct and not written continuously.

            Format your response exactly as:
            SUMMARY: [your detailed article with clear paragraphs]

            Text to process: {content[:15000]}
            """
            
            english_result = await self.call_gemini_api(english_prompt)
            
            # Kiểm tra độ dài tóm tắt
            word_count = len(english_result.split())
            while word_count < 500:  # Thêm vòng lặp để yêu cầu thêm nội dung nếu cần
                expand_prompt = f"""
                The current summary is too short ({word_count} words). 
                Please expand this summary to be over 500 words using the following text:
                {content[:15000]}
                Ensure that the summary is divided into clear paragraphs.
                """
                english_result = await self.call_gemini_api(expand_prompt)
                word_count = len(english_result.split())
            
            # Bước 2: Dịch sang tiếng Việt với yêu cầu tiêu đề thu hút dưới 15 từ
            vietnamese_prompt = f"""
            Translate this English summary to Vietnamese.
            Create a compelling title with less than 15 words.
            Ensure that the summary is divided into clear paragraphs.

            Format your response exactly as:
            TITLE: [Vietnamese compelling title]
            SUMMARY: [Vietnamese detailed article with clear paragraphs]

            English text:
            SUMMARY: {english_result}
            """
            
            vietnamese_result = await self.call_gemini_api(vietnamese_prompt)
            
            # Kiểm tra số từ của kết quả tiếng Việt
            vi_summary = vietnamese_result.split('SUMMARY:')[1].strip()
            vi_word_count = len(vi_summary.split())
            while vi_word_count < 500:  # Kiểm tra số từ sau khi dịch
                expand_vn_prompt = f"""
                The current Vietnamese summary is too short ({vi_word_count} words). 
                Please expand this summary to be over 500 words using the following text:
                {english_result}
                Ensure that the summary is divided into clear paragraphs.
                """
                vietnamese_result = await self.call_gemini_api(expand_vn_prompt)
                vi_summary = vietnamese_result.split('SUMMARY:')[1].strip()
                vi_word_count = len(vi_summary.split())
            
            try:
                vi_title = vietnamese_result.split('TITLE:')[1].split('SUMMARY:')[0].strip()
                
                return {
                    'title': vi_title,
                    'content': vi_summary,
                    'word_count': vi_word_count,
                    'original_urls': urls
                }
                
            except Exception as e:
                raise Exception(f"Không thể parse kết quả tiếng Việt: {str(e)}")
            
        except Exception as e:
            raise Exception(f"Lỗi xử lý Gemini: {str(e)}")

    async def refine_summary(self, summary):
        """
        Chỉnh sửa nội dung tóm tắt để giống một bài báo hơn
        """
        prompt = f"""
        Please refine the following summary to make it sound more like a professional article. 
        Ensure that the language is formal, coherent, and engaging.
        Do not include any headings, subheadings, or bullet points.

        Current summary:
        {summary}
        """
        refined_summary = await self.call_gemini_api(prompt)
        return refined_summary

async def process_and_update_ui(summarizer, urls):
    try:
        result = await summarizer.process_urls(urls)
        return result
    except Exception as e:
        raise e

async def main():
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
                result = await process_and_update_ui(st.session_state.summarizer, urls)
                
                if result:
                    progress_bar.progress(100, text="Hoàn thành!")
                    st.success(f"✅ Tóm tắt thành công! (Độ dài: {result['word_count']} từ tiếng Việt)")
                    
                    st.markdown(f"## 📌 {result['title']}")
                    st.markdown("### 📄 Bản tóm tắt")
                    st.write(result['content'])
                    
                    with st.expander("Xem URLs gốc"):
                        for i, url in enumerate(result['original_urls'], 1):
                            st.write(f"Bài {i}: [{url}]({url})", unsafe_allow_html=True)
                            
            except Exception as e:
                st.error(f"Có lỗi xảy ra: {str(e)}")
            finally:
                progress_bar.empty()

if __name__ == "__main__":
    asyncio.run(main())  # Sử dụng asyncio.run cho hàm main
