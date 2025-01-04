import streamlit as st
import google.generativeai as genai
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import base64
from io import BytesIO
from PIL import Image

def check_api_key():
    """
    Kiểm tra API key Gemini
    """
    try:
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            st.error("⚠️ Vui lòng cấu hình GEMINI_API_KEY trong Streamlit Secrets!")
            st.stop()
        return api_key
    except Exception as e:
        st.error(f"⚠️ Lỗi khi đọc GEMINI_API_KEY: {str(e)}")
        st.stop()

def validate_url(url):
    """
    Kiểm tra URL hợp lệ
    """
    try:
        result = urlparse(url.strip())
        return all([result.scheme in ['http', 'https'], result.netloc])
    except:
        return False

class NewsArticleGenerator:
    def __init__(self):
        self.gemini_api_key = check_api_key()
        genai.configure(api_key=self.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8',
            'Connection': 'keep-alive'
        }
        self.session = None

    async def get_session(self):
        """
        Tạo và tái sử dụng session
        """
        if self.session is None:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session

    async def fetch_url(self, url):
        """
        Đọc nội dung từ URL với xử lý lỗi tốt hơn
        """
        try:
            session = await self.get_session()
            async with session.get(url.strip(), timeout=30) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}")
                return await response.text()
        except asyncio.TimeoutError:
            raise Exception("Timeout khi đọc URL")
        except Exception as e:
            raise Exception(f"Lỗi khi đọc URL: {str(e)}")

    async def fetch_image(self, url):
        """
        Tải ảnh từ URL với xử lý lỗi tốt hơn
        """
        try:
            session = await self.get_session()
            async with session.get(url.strip(), timeout=20) as response:
                if response.status == 200:
                    content_type = response.headers.get('content-type', '')
                    if not content_type.startswith('image/'):
                        return None
                    return await response.read()
                return None
        except Exception as e:
            st.warning(f"⚠️ Lỗi khi tải hình ảnh từ {url}: {str(e)}")
            return None

    def extract_content(self, html):
        """
        Trích xuất nội dung và hình ảnh với cải thiện
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Loại bỏ các phần không cần thiết
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe', 'aside', 'form', 'button']):
                tag.decompose()
            
            # Lấy tiêu đề với nhiều pattern phổ biến
            title_tags = soup.find_all(['h1', 'meta'], attrs={'property': ['og:title', 'twitter:title']})
            title = next((tag.get('content', '') if tag.name == 'meta' else tag.get_text() 
                         for tag in title_tags if tag), '')
            if not title and soup.title:
                title = soup.title.get_text()
            
            # Lấy nội dung chính với nhiều pattern
            content_tags = []
            for tag in soup.find_all(['article', 'main', 'div']):
                if any(c in (tag.get('class', []) + [tag.get('id', '')]) 
                       for c in ['content', 'article', 'post', 'detail', 'body']):
                    content_tags.append(tag)
            
            content = ""
            if content_tags:
                for tag in content_tags:
                    paragraphs = tag.find_all(['p', 'div'], recursive=False)
                    content += ' '.join(p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 100)
            else:
                paragraphs = soup.find_all('p')
                content = ' '.join(p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 100)

            # Lấy hình ảnh có kích thước phù hợp
            images = []
            for img in soup.find_all('img'):
                src = img.get('src', '') or img.get('data-src', '')
                if src and src.startswith(('http', '//')):
                    if not src.startswith('http'):
                        src = 'https:' + src
                    width = img.get('width', '0')
                    height = img.get('height', '0')
                    try:
                        w = int(width)
                        h = int(height)
                        if w < 200 or h < 200:  # Bỏ qua ảnh nhỏ
                            continue
                    except:
                        pass
                    alt = img.get('alt', '') or img.get('title', '')
                    images.append({
                        'url': src,
                        'alt': alt
                    })
            
            return {
                'title': title.strip(),
                'content': content.strip(),
                'images': images[:3]
            }
            
        except Exception as e:
            raise Exception(f"Lỗi khi xử lý HTML: {str(e)}")

    async def close(self):
        """
        Đóng session khi kết thúc
        """
        if self.session:
            await self.session.close()
            self.session = None

    async def scrape_articles(self, urls):
        """
        Thu thập nội dung từ nhiều URLs
        """
        try:
            articles = []
            for url in urls:
                if url.strip():
                    html = await self.fetch_url(url)
                    if not html:
                        continue
                    
                    content = self.extract_content(html)
                    if not content['content']:
                        continue
                        
                    # Tải các hình ảnh
                    images = []
                    for img in content['images']:
                        img_data = await self.fetch_image(img['url'])
                        if img_data:
                            images.append({
                                'data': img_data,
                                'alt': img['alt']
                            })
                    
                    articles.append({
                        'url': url,
                        'title': content['title'],
                        'content': content['content'],
                        'images': images
                    })
            return articles
        finally:
            await self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    async def call_gemini_api(self, prompt):
        """
        Gọi Gemini API với retry và xử lý lỗi tốt hơn
        """
        try:
            response = self.model.generate_content(prompt)
            if not response or not response.text:
                raise Exception("Không nhận được phản hồi từ API")
            return response.text
        except Exception as e:
            if "429" in str(e):
                st.warning("⏳ Đang chờ API... Vui lòng đợi trong giây lát")
                time.sleep(5)
            raise Exception(f"Lỗi API: {str(e)}")

    async def generate_article(self, articles):
        """
        Tạo bài báo với prompt được cải thiện
        """
        try:
            if not articles:
                raise Exception("Không có bài báo nào để tổng hợp")
                
            # Tổng hợp nội dung từ các bài báo
            combined_content = "\n\n---\n\n".join(
                f"Tiêu đề: {a['title']}\nNội dung: {a['content'][:2000]}"  # Giới hạn độ dài để tránh quá tải
                for a in articles
            )

            # Prompt được cải thiện
            analysis_prompt = f"""
            Hãy phân tích và tổng hợp thành một bài báo mới từ các nguồn sau:

            {combined_content}

            Yêu cầu cụ thể:

            1. Tiêu đề (tối đa 15 từ):
               - Súc tích, thu hút nhưng không giật gân
               - Phản ánh chính xác nội dung chính
               - Dùng từ ngữ báo chí chuẩn mực

            2. Cấu trúc:
               - Tóm tắt (3-4 câu) nêu ý chính
               - Triển khai theo trình tự logic
               - Dẫn nguồn khi trích dẫn
               - Phân tích khách quan, đa chiều
               - Kết luận ngắn gọn, đầy đủ

            3. Nội dung (800-1000 từ):
               - Tổng hợp và xác thực thông tin
               - Cân bằng các góc nhìn
               - Số liệu, dữ liệu cụ thể
               - Chú thích hình ảnh phù hợp

            4. Văn phong:
               - Trong sáng, chuyên nghiệp
               - Khách quan, phi thiên kiến
               - Từ ngữ chính xác, dễ hiểu
               - Đảm bảo tính báo chí

            Định dạng phản hồi:
            TITLE: [tiêu đề]

            ARTICLE: [nội dung]
            """

            # Gọi API để tạo bài báo
            result = await self.call_gemini_api(analysis_prompt)
            
            try:
                # Xử lý kết quả
                parts = result.split('TITLE:', 1)
                if len(parts) != 2:
                    raise Exception("Định dạng kết quả không hợp lệ")
                
                content_parts = parts[1].split('ARTICLE:', 1)
                if len(content_parts) != 2:
                    raise Exception("Định dạng kết quả không hợp lệ")
                
                title = content_parts[0].strip()
                content = content_parts[1].strip()
                
                # Kiểm tra và tối ưu tiêu đề nếu cần
                if len(title.split()) > 15:
                    title_prompt = f"""
                    Tối ưu tiêu đề sau (tối đa 15 từ):
                    {title}

                    Yêu cầu:
                    - Ngắn gọn, đầy đủ ý
                    - Thu hút, chuyên nghiệp
                    - Từ ngữ chính xác

                    Trả về: TITLE: [tiêu đề mới]
                    """
                    title_result = await self.call_gemini_api(title_prompt)
                    if 'TITLE:' in title_result:
                        title = title_result.split('TITLE:')[1].strip()
                
                return {
                    'title': title,
                    'content': content,
                    'word_count': len(content.split()),
                    'sources': [a['url'] for a in articles],
                    'images': [img for a in articles for img in a['images']]
                }
                
            except Exception as e:
                raise Exception(f"Lỗi khi xử lý kết quả: {str(e)}")
            
        except Exception as e:
            raise Exception(f"Lỗi khi tạo bài báo: {str(e)}")

def main():
    st.set_page_config(
        page_title="Tổng Hợp Tin Tức", 
        page_icon="📰",
        layout="wide"
    )
    
    st.title("📰 Ứng Dụng Tổng Hợp Tin Tức")
    st.markdown("""
    ### Giới thiệu
    Ứng dụng này giúp tổng hợp và viết lại nội dung từ nhiều bài báo thành một bài báo mới, 
    đảm bảo tính chuyên nghiệp và chất lượng thông qua công nghệ AI.
    
    #### Cách sử dụng:
    1. Nhập URL của các bài báo muốn tổng hợp (tối thiểu 1 bài)
    2. Nhấn "Tạo Bài Báo" và đợi trong giây lát
    3. Xem kết quả và tải xuống theo định dạng mong muốn
    """)
    st.markdown("---")

    if 'generator' not in st.session_state:
        st.session_state.generator = NewsArticleGenerator()

    with st.container():
        st.subheader("🔗 Nhập URLs Bài Báo")
        
        # Tạo 3 cột để nhập URL
        cols = st.columns(3)
        urls = []
        for i, col in enumerate(cols, 1):
            with col:
                url = st.text_input(
                    f"URL bài báo {i}",
                    key=f"url{i}",
                    placeholder="https://..."
                )
                if url:
                    if not validate_url(url):
                        st.error(f"⚠️ URL {i} không hợp lệ!")
                    else:
                        urls.append(url)

        if not urls:
            st.warning("⚠️ Vui lòng nhập ít nhất một URL bài báo!")
            st.stop()

        if st.button("🔄 Tạo Bài Báo", type="primary"):
            with st.spinner("⏳ Đang tổng hợp nội dung..."):
                try:
                    # Tạo và hiển thị thanh tiến trình
                    progress_bar = st.progress(0)
                    
                    # Thu thập nội dung từ các URLs
                    articles = asyncio.run(st.session_state.generator.scrape_articles(urls))
                    progress_bar.progress(50)
                    
                    if not articles:
                        st.error("❌ Không thể đọc được nội dung từ các URL đã nhập!")
                        st.stop()
                    
                    # Tạo bài báo mới
                    result = asyncio.run(st.session_state.generator.generate_article(articles))
                    progress_bar.progress(100)
                    
                    # Hiển thị kết quả
                    st.success("✅ Đã tạo bài báo thành công!")
                    
                    # Container cho bài báo
                    with st.container():
                        st.markdown("---")
                        st.subheader("📝 Bài Báo Đã Tạo")
                        
                        # Hiển thị tiêu đề
                        st.markdown(f"## {result['title']}")
                        
                        # Hiển thị hình ảnh nếu có
                        if result['images']:
                            cols = st.columns(min(3, len(result['images'])))
                            for idx, (col, img) in enumerate(zip(cols, result['images'])):
                                with col:
                                    try:
                                        image = Image.open(BytesIO(img['data']))
                                        st.image(image, caption=img['alt'] if img['alt'] else f"Hình {idx + 1}")
                                    except Exception:
                                        st.warning("⚠️ Không thể hiển thị hình ảnh")
                        
                        # Hiển thị nội dung
                        st.markdown(result['content'])
                        
                        # Thông tin thêm
                        st.markdown("---")
                        st.markdown(f"**Số từ:** {result['word_count']}")
                        st.markdown("**Nguồn tham khảo:**")
                        for url in result['sources']:
                            st.markdown(f"- {url}")
                        
                        # Tải xuống
                        st.markdown("---")
                        st.subheader("💾 Tải xuống")
                        
                        # Tạo nội dung Markdown
                        markdown_content = f"""# {result['title']}\n\n{result['content']}\n\n---\n
Số từ: {result['word_count']}\n\nNguồn tham khảo:\n""" + "\n".join(f"- {url}" for url in result['sources'])
                        
                        # Tạo button tải xuống
                        markdown_bytes = markdown_content.encode()
                        b64 = base64.b64encode(markdown_bytes).decode()
                        href = f'data:text/markdown;base64,{b64}'
                        st.markdown(f'<a href="{href}" download="bao_tong_hop.md" class="button">📥 Tải xuống định dạng Markdown</a>', unsafe_allow_html=True)
                        
                except Exception as e:
                    st.error(f"❌ Lỗi: {str(e)}")
                    st.stop()

if __name__ == "__main__":
    main()
    
