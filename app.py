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
                *[self.extract_content_from_url(url.strip()) for url in urls]
            )
            
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
            Create a compelling title and summary for this Vietnamese text.

            Title requirements:
            1. Maximum 15 words
            2. Must be attention-grabbing and engaging
            3. Use strong action words
            4. Create curiosity but avoid clickbait
            5. Include key insights or numbers if relevant
            6. Be specific and clear
            
            Summary requirements:
            1. 500-1000 words
            2. Comprehensive coverage
            3. Clear structure

            Format your response exactly as:
            TITLE: [your compelling title]
            SUMMARY: [your summary]

            Text to process: {content[:15000]}
            """
            
            english_result = await self.call_gemini_api(english_prompt)
            
            try:
                en_title = english_result.split('TITLE:')[1].split('SUMMARY:')[0].strip()
                en_summary = english_result.split('SUMMARY:')[1].strip()
                
                # Kiểm tra và tối ưu tiêu đề tiếng Anh
                title_words = len(en_title.split())
                if title_words > 15:
                    title_prompt = f"""
                    Create a more impactful and shorter title (max 15 words).
                    
                    Requirements:
                    1. Be more concise and punchy
                    2. Use strong action verbs
                    3. Create immediate interest
                    4. Focus on the most compelling angle
                    5. Include key numbers or insights if relevant
                    
                    Current title ({title_words} words): {en_title}
                    
                    Format: TITLE: [your shorter, more compelling title]
                    """
                    title_response = await self.call_gemini_api(title_prompt)
                    en_title = title_response.split('TITLE:')[1].strip()
                
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
            
            # Bước 2: Dịch sang tiếng Việt với yêu cầu tiêu đề thu hút
            vietnamese_prompt = f"""
            Translate this English title and summary to Vietnamese.
            
            For the title:
            1. Maximum 15 words
            2. Must be compelling and attention-grabbing
            3. Use strong Vietnamese action words
            4. Create curiosity while maintaining credibility
            5. Adapt any numbers or key insights naturally
            6. Keep the core message but optimize for Vietnamese readers
            
            Format your response exactly as:
            TITLE: [Vietnamese compelling title]
            SUMMARY: [Vietnamese summary]

            English text:
            TITLE: {en_title}
            SUMMARY: {en_summary}
            """
            
            vietnamese_result = await self.call_gemini_api(vietnamese_prompt)
            
            try:
                vi_title = vietnamese_result.split('TITLE:')[1].split('SUMMARY:')[0].strip()
                vi_summary = vietnamese_result.split('SUMMARY:')[1].strip()
                
                # Kiểm tra độ dài bản tóm tắt tiếng Việt
                vi_word_count = len(vi_summary.split())
                if vi_word_count < 500:
                    expand_vi_prompt = f"""
                    Hãy mở rộng bản tóm tắt tiếng Việt này để đạt tối thiểu 500 từ.
                    
                    Yêu cầu:
                    1. Giữ nguyên ý chính và cấu trúc hiện tại
                    2. Bổ sung thêm:
                       - Chi tiết và ví dụ cụ thể
                       - Phân tích sâu hơn về các điểm chính
                       - Bối cảnh và thông tin liên quan
                       - Tác động và ý nghĩa của vấn đề
                    3. Đảm bảo văn phong mạch lạc, dễ đọc
                    4. Tránh lặp lại thông tin
                    
                    B���n tóm tắt hiện tại ({vi_word_count} từ):
                    {vi_summary}
                    
                    Format: Trả về bản tóm tắt mở rộng, không cần tiêu đề.
                    """
                    
                    expanded_vi_summary = await self.call_gemini_api(expand_vi_prompt)
                    vi_summary = expanded_vi_summary.strip()
                    vi_word_count = len(vi_summary.split())
                    
                    # Kiểm tra lại sau khi mở rộng
                    if vi_word_count < 500:
                        detail_prompt = f"""
                        Bản tóm tắt vẫn chưa đủ 500 từ. Hãy bổ sung, phân tích triển khai nội dung và bỏ tiêu đề các mục nhỏ
                        
                        Bản hiện tại ({vi_word_count} từ):
                        {vi_summary}
                        """
                        
                        final_vi_summary = await self.call_gemini_api(detail_prompt)
                        vi_summary = final_vi_summary.strip()
                        vi_word_count = len(vi_summary.split())
                
                # Kiểm tra và tối ưu tiêu đề tiếng Việt
                vi_title_words = len(vi_title.split())
                if vi_title_words > 15:
                    vi_title_prompt = f"""
                    Tạo tiêu đề hấp dẫn và ngắn gọn hơn (tối đa 15 từ).
                    Yêu cầu:
                    1. Sử dụng từ ngữ mạnh mẽ, thu hút
                    2. Tạo sự tò mò ngay lập tức
                    3. Tập trung vào góc độ thú vị nhất
                    4. Đưa số liệu hoặc insight quan trọng (nếu có)
                    5. Ngắn gọn nhưng đầy đủ ý
                    
                    Tiêu đề hiện tại ({vi_title_words} từ): {vi_title}
                    
                    Format: TITLE: [tiêu đề mới thu hút hơn]
                    """
                    vi_title_response = await self.call_gemini_api(vi_title_prompt)
                    vi_title = vi_title_response.split('TITLE:')[1].strip()
                
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
                            st.write(f"Bài {i}: [{url}]({url})", unsafe_allow_html=True)
                            
            except Exception as e:
                st.error(f"Có lỗi xảy ra: {str(e)}")
            finally:
                progress_bar.empty()

if __name__ == "__main__":
    main()
