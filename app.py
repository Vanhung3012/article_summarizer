import streamlit as st
import google.generativeai as genai
import aiohttp
import asyncio
import newspaper
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import time
import os
import nltk
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# Download required NLTK data
try:
    nltk.data.find('punkt')
except LookupError:
    nltk.download('punkt')

class ArticleSummarizer:
    def __init__(self):
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        if not self.gemini_api_key:
            raise ValueError("Không tìm thấy GEMINI_API_KEY trong biến môi trường")
        genai.configure(api_key=self.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
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

    def parse_article(self, html, url):
        """
        Sử dụng newspaper3k để parse nội dung bài báo
        """
        try:
            article = newspaper.Article(url)
            article.download(input_html=html)
            article.parse()
            return {
                'title': article.title,
                'text': article.text
            }
        except Exception as e:
            raise Exception(f"Lỗi khi parse bài báo: {str(e)}")

    async def extract_content_from_url(self, url):
        """
        Trích xuất nội dung từ URL với tối ưu tốc độ
        """
        html = await self.fetch_url(url)
        with ThreadPoolExecutor() as executor:
            article_content = await asyncio.get_event_loop().run_in_executor(
                executor, 
                self.parse_article, 
                html, 
                url
            )
        return article_content['text']

    async def process_urls(self, urls):
        """
        Xử lý nhiều URLs đồng thời
        """
        try:
            start_time = time.time()
            
            # Đọc nội dung từ tất cả URLs đồng thời
            contents = await asyncio.gather(
                *[self.extract_content_from_url(url.strip()) for url in urls]
            )
            
            # Kết hợp nội dung
            combined_content = "\n\n---\n\n".join(contents)
            
            print(f"Thời gian đọc URLs: {time.time() - start_time:.2f} giây")
            
            # Xử lý với Gemini
            result = await self.process_content(combined_content)
            
            print(f"Tổng thời gian xử lý: {time.time() - start_time:.2f} giây")
            
            return {
                **result,
                'original_urls': urls
            }
                
        except Exception as e:
            raise Exception(f"Lỗi: {str(e)}")

    async def process_content(self, content):
        """
        Xử lý nội dung với Gemini và đảm bảo độ dài tối thiểu
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

            Text to process: {content}
            """
            
            english_response = self.model.generate_content(english_prompt)
            english_result = english_response.text
            
            # Parse kết quả tiếng Anh
            try:
                en_title = english_result.split('TITLE:')[1].split('SUMMARY:')[0].strip()
                en_summary = english_result.split('SUMMARY:')[1].strip()
                
                # Kiểm tra độ dài của bản tóm tắt (tính theo số từ)
                word_count = len(en_summary.split())
                
                # Nếu dưới 500 từ, yêu cầu Gemini mở rộng nội dung
                if word_count < 500:
                    expand_prompt = f"""
                    The current summary is too short ({word_count} words). 
                    Please expand this summary to be between 500-1000 words by:
                    1. Adding more detailed analysis
                    2. Including relevant context and background information
                    3. Providing more specific examples and explanations
                    4. Elaborating on key points
                    
                    Current summary:
                    {en_summary}
                    """
                    
                    expand_response = self.model.generate_content(expand_prompt)
                    en_summary = expand_response.text
                    
                    # Kiểm tra lại độ dài sau khi mở rộng
                    new_word_count = len(en_summary.split())
                    print(f"Đã mở rộng nội dung từ {word_count} từ lên {new_word_count} từ")
                
            except Exception as e:
                raise Exception(f"Không thể parse kết quả tiếng Anh: {str(e)}")
            
            # Bước 2: Dịch sang tiếng Việt
            vietnamese_prompt = f"""
            Translate this English title and summary to Vietnamese.
            Ensure the translation maintains the detailed and comprehensive nature of the content.
            
            Format your response exactly as:
            TITLE: [Vietnamese title]
            SUMMARY: [Vietnamese summary]

            English text:
            TITLE: {en_title}
            SUMMARY: {en_summary}
            """
            
            vietnamese_response = self.model.generate_content(vietnamese_prompt)
            vietnamese_result = vietnamese_response.text
            
            # Parse kết quả tiếng Việt
            try:
                vi_title = vietnamese_result.split('TITLE:')[1].split('SUMMARY:')[0].strip()
                vi_summary = vietnamese_result.split('SUMMARY:')[1].strip()
                
                # Thêm thông tin về độ dài vào kết quả
                word_count_vi = len(vi_summary.split())
                print(f"Độ dài bản dịch tiếng Việt: {word_count_vi} từ")
                
            except Exception as e:
                raise Exception(f"Không thể parse kết quả tiếng Việt: {str(e)}")
            
            return {
                'title': vi_title,
                'content': vi_summary,
                'english_title': en_title,
                'english_summary': en_summary,
                'word_count': word_count_vi  # Thêm thông tin về số từ
            }
            
        except Exception as e:
            raise Exception(f"Lỗi xử lý Gemini: {str(e)}")

def validate_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

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
                    st.success(f"✅ Tóm tắt thành công! (Độ dài: {result['word_count']} từ)")
                    
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
