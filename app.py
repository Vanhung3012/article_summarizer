import streamlit as st
import google.generativeai as genai
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time
from tenacity import retry, stop_after_attempt, wait_exponential

def check_api_key():
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
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url) as response:
                    return await response.text(), url
        except Exception as e:
            raise Exception(f"Lỗi khi đọc URL {url}: {str(e)}")

    def extract_content(self, html, url):
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe', 'aside']):
                tag.decompose()

            title = ""
            if soup.find('h1'):
                title = soup.find('h1').get_text().strip()
            elif soup.find('title'):
                title = soup.find('title').get_text().strip()

            images = []
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        parsed_url = urlparse(url)
                        src = f"{parsed_url.scheme}://{parsed_url.netloc}{src}"
                    
                    if not any(x in src.lower() for x in ['avatar', 'logo', 'icon', 'ads', 'banner']):
                        alt = img.get('alt', '')
                        if len(src) > 10 and src.startswith(('http://', 'https://')):
                            images.append({
                                'src': src,
                                'alt': alt
                            })

            article_tags = soup.find_all(['article', 'main', 'div'], class_=['content', 'article', 'post'])
            content = ""
            
            if article_tags:
                for tag in article_tags:
                    paragraphs = tag.find_all('p')
                    content += ' '.join([p.get_text().strip() for p in paragraphs])
            else:
                paragraphs = soup.find_all('p')
                content = ' '.join([p.get_text().strip() for p in paragraphs])

            return {
                'title': title,
                'content': content,
                'images': images[:5],
                'url': url
            }
            
        except Exception as e:
            raise Exception(f"Lỗi khi xử lý HTML: {str(e)}")

    async def scrape_articles(self, urls):
        articles = []
        tasks = [self.fetch_url(url) for url in urls if url.strip()]
        results = await asyncio.gather(*tasks)
        
        for html, url in results:
            content = self.extract_content(html, url)
            articles.append(content)
        return articles

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def call_gemini_api(self, prompt):
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
        try:
            combined_content = "\n\n---\n\n".join(
                [f"Tiêu đề: {a['title']}\nNội dung: {a['content']}\nHình ảnh: {', '.join([img['alt'] for img in a['images']])}" 
                 for a in articles]
            )

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

            5. Xử lý hình ảnh:
               - Chọn tối đa 5 hình ảnh phù hợp
               - Sắp xếp theo thứ tự quan trọng
               - Viết chú thích cho mỗi hình
               - Đảm bảo tính liên quan và chất lượng

            Format phản hồi:
            TITLE: [tiêu đề bài báo]
            ARTICLE: [nội dung bài báo]
            IMAGES: [danh sách index hình ảnh được chọn và chú thích mới]
            """

            result = await self.call_gemini_api(analysis_prompt)
            
            title = result.split('TITLE:')[1].split('ARTICLE:')[0].strip()
            content = result.split('ARTICLE:')[1].split('IMAGES:')[0].strip()
            image_selections = result.split('IMAGES:')[1].strip().split('\n')

            selected_images = []
            all_images = []
            for article in articles:
                all_images.extend(article['images'])

            for selection in image_selections:
                if ':' in selection:
                    idx, caption = selection.split(':', 1)
                    try:
                        idx = int(idx.strip())
                        if 0 <= idx < len(all_images):
                            image = all_images[idx].copy()
                            image['caption'] = caption.strip()
                            selected_images.append(image)
                    except ValueError:
                        continue

            return {
                'title': title,
                'content': content,
                'images': selected_images[:5],
                'word_count': len(content.split()),
                'sources': [a['url'] for a in articles]
            }
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
    Ứng dụng tổng hợp và viết lại nội dung từ nhiều bài báo thành một bài báo mới,
    kèm theo hình ảnh minh họa.
    """)
    st.markdown("---")

    if 'generator' not in st.session_state:
        st.session_state.generator = NewsArticleGenerator()

    with st.container():
        st.subheader("🔗 Nhập URLs Bài Báo")
        
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
        
        if st.button("Tạo Bài Báo", type="primary"):
            valid_urls = [url for url in urls if url.strip()]
            if len(valid_urls) == 0:
                st.warning("⚠️ Vui lòng nhập ít nhất một URL!")
                return
                
            invalid_urls = [url for url in valid_urls if not validate_url(url)]
            if invalid_urls:
                st.error(f"❌ URL không hợp lệ: {', '.join(invalid_urls)}")
                return
            
            progress = st.progress(0)
            status = st.empty()
            
            try:
                with st.spinner("Đang xử lý..."):
                    status.text("Đang đọc nội dung từ các URLs...")
                    progress.progress(25)
                    
                    articles = asyncio.run(
                        st.session_state.generator.scrape_articles(valid_urls)
                    )
                    
                    if not articles:
                        st.error("❌ Không thể đọc nội dung từ các URLs!")
                        return
                    
                    status.text("Đang tổng hợp và viết bài...")
                    progress.progress(50)
                    
                    result = asyncio.run(
                        st.session_state.generator.generate_article(articles)
                    )
                    
                    if result:
                        progress.progress(100)
                        status.empty()
                        
                        st.success(f"✅ Đã tạo bài báo thành công! ({result['word_count']} từ)")
                        
                        st.markdown(f"## 📌 {result['title']}")
                        
                        if result['images']:
                            st.image(
                                result['images'][0]['src'],
                                caption=result['images'][0].get('caption', ''),
                                use_column_width=True
                            )
                        
                        st.markdown("### 📄 Nội dung")
                        st.write(result['content'])
                        
                        if len(result['images']) > 1:
                            st.markdown("### 🖼️ Hình ảnh liên quan")
                            cols = st.columns(2)
                            for i, img in enumerate(result['images'][1:], 1):
                                with cols[i % 2]:
                                    st.image(
                                        img['src'],
                                        caption=img.get('caption', ''),
                                        use_column_width=True
                                    )
                        
                        with st.expander("🔍 Xem nguồn bài viết"):
                            for i, url in enumerate(result['sources'], 1):
                                st.write(f"{i}. [{url}]({url})")
                        
            except Exception as e:
                st.error(f"❌ Có lỗi xảy ra: {str(e)}")
            finally:
                progress.empty()
                status.empty()

if __name__ == "__main__":
    main()
