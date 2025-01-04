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
        api_key = st.secrets["GEMINI_API_KEY"]
        if not api_key:
            st.error("⚠️ Vui lòng cấu hình GEMINI_API_KEY!")
            st.stop()
        return api_key
    except Exception as e:
        st.error("⚠️ GEMINI_API_KEY chưa được cấu hình trong Streamlit Secrets!")
        st.stop()

def validate_url(url):
    """
    Kiểm tra URL hợp lệ
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

class NewsArticleGenerator:
    def __init__(self):
        self.gemini_api_key = check_api_key()
        genai.configure(api_key=self.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    async def fetch_url(self, url):
        """
        Đọc nội dung từ URL
        """
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url) as response:
                    return await response.text()
        except Exception as e:
            raise Exception(f"Lỗi khi đọc URL {url}: {str(e)}")

    async def fetch_image(self, url):
        """
        Tải ảnh từ URL
        """
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.read()
                    return None
        except:
            return None

    def extract_content(self, html):
        """
        Trích xuất nội dung và hình ảnh từ HTML
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Loại bỏ các phần không cần thiết
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe', 'aside']):
                tag.decompose()
            
            # Lấy tiêu đề
            title = ""
            if soup.find('h1'):
                title = soup.find('h1').get_text().strip()
            elif soup.find('title'):
                title = soup.find('title').get_text().strip()
            
            # Lấy nội dung chính
            article_tags = soup.find_all(['article', 'main', 'div'], class_=['content', 'article', 'post'])
            content = ""
            
            if article_tags:
                for tag in article_tags:
                    paragraphs = tag.find_all('p')
                    content += ' '.join([p.get_text().strip() for p in paragraphs])
            else:
                paragraphs = soup.find_all('p')
                content = ' '.join([p.get_text().strip() for p in paragraphs])

            # Lấy hình ảnh
            images = []
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if src and src.startswith('http'):
                    alt = img.get('alt', '')
                    images.append({
                        'url': src,
                        'alt': alt
                    })
            
            return {
                'title': title,
                'content': content,
                'images': images[:3]  # Giới hạn 3 ảnh cho mỗi bài
            }
            
        except Exception as e:
            raise Exception(f"Lỗi khi xử lý HTML: {str(e)}")

    async def scrape_articles(self, urls):
        """
        Thu thập nội dung từ nhiều URLs
        """
        articles = []
        for url in urls:
            if url.strip():
                html = await self.fetch_url(url)
                content = self.extract_content(html)
                
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    async def call_gemini_api(self, prompt):
        """
        Gọi Gemini API với retry
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            if "429" in str(e):
                st.warning("Đang chờ API... Vui lòng đợi trong giây lát")
                time.sleep(5)
                raise e
            raise e

    async def generate_article(self, articles):
        """
        Tạo bài báo từ nhiều nguồn
        """
        try:
            # Tổng hợp nội dung từ các bài báo
            combined_content = "\n\n---\n\n".join(
                [f"Tiêu đề: {a['title']}\nNội dung: {a['content']}" for a in articles]
            )

            # Prompt để phân tích và tổng hợp thành bài báo mới
            analysis_prompt = f"""
            Phân tích và tổng hợp thành một bài báo mới từ các nguồn sau:

            {combined_content}

            Yêu cầu:

            1. Tiêu đề bài báo:
               - Tối đa 15 từ
               - Thu hút, tạo ấn tượng mạnh
               - Phản ánh chính xác nội dung chính
               - Sử dụng từ ngữ báo chí chuẩn mực
               - Tránh giật gân, câu view

            2. Cấu trúc bài viết:
               - Tóm tắt ý chính trong đoạn mở đầu (3-4 câu)
               - Triển khai chi tiết theo logic rõ ràng
               - Dẫn nguồn và trích dẫn khi cần
               - Phân tích, đánh giá khách quan
               - Kết luận súc tích, đầy đủ
               - Chèn chú thích cho hình ảnh phù hợp vào vị trí thích hợp trong bài viết

            3. Nội dung:
               - Tổng hợp thông tin từ nhiều nguồn
               - Đảm bảo tính chính xác
               - Cung cấp góc nhìn đa chiều
               - Thêm số liệu, dữ liệu cụ thể
               - Độ dài 800-1000 từ

            4. Ngôn ngữ:
               - Trong sáng, dễ hiểu
               - Phong cách báo chí chuyên nghiệp
               - Khách quan, trung lập
               - Tránh từ ngữ cảm xúc, thiên kiến
               - Chọn lọc từ ngữ phù hợp văn phong

            Format phản hồi:
            TITLE: [tiêu đề bài báo]
            ARTICLE: [nội dung bài báo]
            """

            # Gọi API để tạo bài báo
            result = await self.call_gemini_api(analysis_prompt)
            
            try:
                title = result.split('TITLE:')[1].split('ARTICLE:')[0].strip()
                content = result.split('ARTICLE:')[1].strip()
                
                # Kiểm tra độ dài tiêu đề
                if len(title.split()) > 15:
                    optimize_title_prompt = f"""
                    Tối ưu tiêu đề sau để ngắn gọn hơn (tối đa 15 từ) nhưng vẫn giữ được ý chính:
                    {title}

                    Yêu cầu:
                    - Rút gọn nhưng không mất ý nghĩa
                    - Vẫn phải thu hút, ấn tượng
                    - Dùng từ ngữ chính xác, súc tích
                    - Phù hợp phong cách báo chí

                    Format: TITLE: [tiêu đề tối ưu]
                    """
                    title_result = await self.call_gemini_api(optimize_title_prompt)
                    title = title_result.split('TITLE:')[1].strip()
                
                # Thu thập tất cả hình ảnh từ các bài báo
                all_images = []
                for article in articles:
                    all_images.extend(article['images'])
                
                return {
                    'title': title,
                    'content': content,
                    'word_count': len(content.split()),
                    'sources': [a['url'] for a in articles],
                    'images': all_images
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
    Ứng dụng này giúp tổng hợp và viết lại nội dung từ nhiều bài báo thành một bài báo mới, 
    đảm bảo tính chuyên nghiệp và chất lượng.
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
                urls.append(url)
        
        # Nút tạo bài báo
        if st.button("Tạo Bài Báo", type="primary"):
            # Kiểm tra URLs
            valid_urls = [url for url in urls if url.strip()]
            if len(valid_urls) == 0:
                st.warning("⚠️ Vui lòng nhập ít nhất một URL!")
                return
                
            invalid_urls = [url for url in valid_urls if not validate_url(url)]
            if invalid_urls:
                st.error(f"❌ URL không hợp lệ: {', '.join(invalid_urls)}")
                return
            
            # Hiển thị thanh tiến trình
            progress = st.progress(0)
            status = st.empty()
            
            try:
                with st.spinner("Đang xử lý..."):
                    # Thu thập nội dung
                    status.text("Đang đọc nội dung và tải hình ảnh từ các URLs...")
                    progress.progress(25)
                    
                    articles = asyncio.run(
                        st.session_state.generator.scrape_articles(valid_urls)
                    )
                    
                    if not articles:
                        st.error("❌ Không thể đọc nội dung từ các URLs!")
                        return
                    
                    # Tạo bài báo
                    status.text("Đang tổng hợp và viết bài...")
                    progress.progress(50)
                    
                    result = asyncio.run(
                        st.session_state.generator.generate_article(articles)
                    )
                    
                    if result:
                        progress.progress(100)
                        status.empty()
                        
                        # Hiển thị kết quả
                        st.success(f"✅ Đã tạo bài báo thành công! ({result['word_count']} từ)")
                        
                        st.markdown(f"## 📌 {result['title']}")
                        
                        # Hiển thị nội dung và hình ảnh
                        content_parts = result['content'].split('\n\n')
                        
                        # Chèn hình ảnh vào giữa các đoạn văn
                        for i, part in enumerate(content_parts):
                            st.write(part)
                            # Chèn ảnh sau mỗi 2-3 đoạn văn
                            if i % 3 == 1 and result['images'] and len(result['images']) > i//3:
                                img = result['images'][i//3]
                                try:
                                    image = Image.open(BytesIO(img['data']))
                                    st.image(image, caption=img['alt'], use_column_width=True)
                                except Exception as e:
                                    st.warning(f"Không thể hiển thị hình ảnh: {str(e)}")
                                    # Hiển thị nguồn tham khảo
                        st.markdown("---")
                        st.markdown("### 📚 Nguồn Tham Khảo")
                        for url in result['sources']:
                            st.markdown(f"- [{url}]({url})")
                        
                        # Tạo nút xuất bài viết
                        st.markdown("---")
                        st.subheader("💾 Tải Xuống")
                        
                        # Tạo nội dung Markdown
                        markdown_content = f"""# {result['title']}\n\n{result['content']}\n\n---\n### Nguồn Tham Khảo\n"""
                        for url in result['sources']:
                            markdown_content += f"- {url}\n"
                        
                        # Tạo nội dung HTML
                        html_content = f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <meta charset="utf-8">
                            <title>{result['title']}</title>
                            <style>
                                body {{
                                    font-family: Arial, sans-serif;
                                    line-height: 1.6;
                                    max-width: 800px;
                                    margin: 0 auto;
                                    padding: 20px;
                                }}
                                img {{
                                    max-width: 100%;
                                    height: auto;
                                    margin: 20px 0;
                                }}
                                .sources {{
                                    margin-top: 40px;
                                    padding-top: 20px;
                                    border-top: 1px solid #ccc;
                                }}
                            </style>
                        </head>
                        <body>
                            <h1>{result['title']}</h1>
                            {result['content'].replace('\n\n', '</p><p>')}
                            <div class="sources">
                                <h3>Nguồn Tham Khảo</h3>
                                <ul>
                                    {''.join([f'<li><a href="{url}">{url}</a></li>' for url in result['sources']])}
                                </ul>
                            </div>
                        </body>
                        </html>
                        """
                        
                        col1, col2 = st.columns(2)
                        
                        # Nút tải Markdown
                        with col1:
                            md_bytes = markdown_content.encode()
                            md_b64 = base64.b64encode(md_bytes).decode()
                            md_href = f'data:text/markdown;base64,{md_b64}'
                            st.download_button(
                                "📝 Tải Markdown",
                                markdown_content,
                                "article.md",
                                "text/markdown",
                                use_container_width=True
                            )
                        
                        # Nút tải HTML
                        with col2:
                            html_bytes = html_content.encode()
                            html_b64 = base64.b64encode(html_bytes).decode()
                            html_href = f'data:text/html;base64,{html_b64}'
                            st.download_button(
                                "🌐 Tải HTML",
                                html_content,
                                "article.html",
                                "text/html",
                                use_container_width=True
                            )
                            
                    else:
                        st.error("❌ Không thể tạo bài báo!")
                        
            except Exception as e:
                st.error(f"❌ Có lỗi xảy ra: {str(e)}")
            finally:
                progress.empty()
                status.empty()

if __name__ == "__main__":
    main()
