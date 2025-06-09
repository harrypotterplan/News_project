import os
import requests
from dotenv import load_dotenv
from flask import Flask
from flask_mysqldb import MySQL
from datetime import datetime
import re
from bs4 import BeautifulSoup
import logging
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer

# .env 파일 로드
load_dotenv()

# Flask 애플리케이션
app = Flask(__name__)


# MySQL 설정
app.config['MYSQL_HOST'] = os.getenv('DB_HOST')
app.config['MYSQL_USER'] = os.getenv('DB_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASS')
app.config['MYSQL_DB'] = os.getenv('DB_NAME')
mysql = MySQL(app)

# 네이버 뉴스 API 설정
NAVER_CLIENT_ID = os.getenv('NAVER_CLIENT_ID')
NAVER_CLIENT_SECRET = os.getenv('NAVER_CLIENT_SECRET')
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

# 검색 키워드
SEARCH_QUERIES = [
    "IT", "경제", "정치", "사회", "문화", "스포츠", "세계", "생활", "기술", "뉴스"
]

# 로깅 설정
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("crawler.log"),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger(__name__)

# KeyBERT 모델 로드
try:
    logger.info("KeyBERT 모델 로딩 중...")
    kw_model = KeyBERT(model=SentenceTransformer('jhgan/ko-sbert-nli'))
    logger.info("KeyBERT 모델 로딩 완료.")
except Exception as e:
    logger.error(f"KeyBERT 모델 로딩 실패: {e}")
    kw_model = None

# 불용어 목록
COMMON_STOPWORDS = set([
    '대한', '우리', '이번', '지난', '동안', '이것', '그것', '저것', '다시', '관련', '위해', '통해', '등', '명', '것', '수', '점', '때', '곳', 
    '바', '및', '위', '중', '이', '그', '지난해', '오늘', '내일', '이날', '해당', '현재', '가지', '이제', '말', '월', '년', '일', '고', '면', 
    '좀', '개', '분', '뒤', '전', '기자', ' ', '습니다', '이다', '겁니다', '것이다', '같다', '일 것이다.', '입니다', '등등','없는', '많은', '모든', 
    '아주', '매우', '정말', '가장', '더욱', '오직', '결국', '물론', '또한', '과연', '단지', '이미', '여전히', '겨우', '그저', '내내', '마침',
    '반드시', '비록', '설마', '아마', '어찌', '어차피', '언제나', '오히려', '원래', '일찍', '자주', '점점', '정작', '하필', '혹시', '계속', '과연', 
    '다만', '따로', '마침내', '무려', '미처', '바깥', '빨리', '어느', '왠지', '이윽고', '조금', '한껏', '혼자', '훨씬', '가까이', '간혹', '결코', 
    '고루', '공교롭게', '굳이', '그만', '극히', '급히', '깜짝', '꾸준히', '늘어', '다가', '다만', '다소', '대개', '더불어', '도저히', '드디어', 
    '드문드문', '두루', '따라서', '딱히', '막상', '먼저','모조리', '무척', '미리', '바야흐로', '벌써', '별로', '보통', '비로소', '오히려', 
    '어쩌면', '어째서', '오로지', '온통', '우연히', '을', '를', '은', '는', '이', '가','와', '과', '도', '만', '요', '죠', '에요', '예요', '해서', 
    '하게', '하고', '거나', '든지', '든지', '부터', '까지', '에게', '한테', '께서', '으로', '로', '에서', '부터', '보다', '처럼', '만큼', '듯이', 
    '뿐', '이다', '입니다', '이다', '다고', '라고', '으로', '러', '면서', '아서', '어서', '니까', '는데', '거든요', '지요', '나요', '인가', 
    '을까', '까', '습니다', 'ㅂ니다', 'ㅂ시다', '어요', '아요', '어요', '해요', '하죠', '어떤', '몇', '어느', '무엇', '누구', '왜', '어디', '어떻게', 
    '얼마나', '언제', '무슨', '아무', '여러분', '그리고', '그러나', '하지만', '또는', '즉', '따라서', '그러므로', '게다가', '더군다나', 
    '아니면', '혹은', '예를', '들면', '즉', '다시', '말해', '결론적으로', '덧붙여', '마지막으로', '우선', '먼저', '다음으로', '또한', 
    '아울러', '아니라', '뿐만', '아니라', '이와', '같이'
])

def extract_keywords_with_keybert(text, num_keywords=5, keyphrase_ngram_range=(1,2)):
    if not text:
        logger.debug("    [KeyBERT Debug] 입력 텍스트가 비어 있습니다. 키워드 추출 스킵.")
        return ""
    clean_text = re.sub(r'<[^>]+>|\s+', ' ', text).strip()
    clean_text = re.sub(r'[^\w\s]', '', clean_text)
    logger.debug(f"    [KeyBERT Debug] 전처리 후 텍스트 길이: {len(clean_text)}. 내용(첫 50자): '{clean_text[:50]}...'")
    if not clean_text:
        logger.debug("    [KeyBERT Debug] 전처리 후 텍스트가 비어 있습니다. 키워드 추출 스킵.")
        return ""
    keywords_with_score = kw_model.extract_keywords(
        clean_text,
        keyphrase_ngram_range=keyphrase_ngram_range,
        stop_words=None,
        top_n=num_keywords * 2
    )
    logger.debug(f"    [KeyBERT Debug] KeyBERT 1차 추출 결과(점수 포함): {keywords_with_score}")
    final_keywords = []
    for keyword, score in keywords_with_score:
        is_stopword_phrase = False
        words_in_keyword = keyword.split()
        if not words_in_keyword:
            continue
        for word in words_in_keyword:
            if word in COMMON_STOPWORDS or len(word) < 2:
                is_stopword_phrase = True
                break
        if not is_stopword_phrase:
            final_keywords.append(keyword)
            if len(final_keywords) >= num_keywords:
                break
    logger.debug(f"    [KeyBERT Debug] 최종 필터링된 키워드: {final_keywords}")
    return ", ".join(final_keywords)

def get_naver_news_content_and_keywords(url):
    global kw_model
    if kw_model is None:
        logger.error("[KeyBERT Error] KeyBERT 모델이 로드되지 않았습니다. 키워드 추출 불가.")
        return None, "키워드 추출 실패: KeyBERT 모델 로드 오류"
    logger.debug(f"\n--- [Crawler Debug] URL 처리 시작: {url}")
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        full_content = ""
        content_div = soup.find('article', id='dic_area')
        if not content_div:
            content_div = soup.find('article', class_='go_trans _article_content')
        if not content_div:
            content_div = soup.find('div', id='dic_area')
        if content_div:
            for img_desc in content_div.find_all('em', class_='img_desc'):
                img_desc.decompose()
            for br in content_div.find_all('br'):
                br.replace_with('\n')
            full_content = content_div.get_text(strip=True)
            full_content = re.sub(r'본문 내용 재생.*', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'^(.*?)\(function', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'flash 오류를 우회하기 위한 함수 추가\.[\s\S]*', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'// flash content end\.[\s\S]*', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'\[.+?\]', '', full_content)
            full_content = re.sub(r'\(.+?\)기자', '', full_content)
            full_content = re.sub(r'저작권자 ⓒ.+?\s', '', full_content)
            full_content = re.sub(r'무단전재 및 재배포 금지\.?', '', full_content)
            full_content = re.sub(r'\S+@\S+\.\S+', '', full_content)
            full_content = re.sub(r'\d{2,4}-\d{3,4}-\d{4}', '', full_content)
            full_content = re.sub(r'\n\s*\n', '\n', full_content)
            full_content = full_content.strip()
        else:
            logging.warning(f"--- [Crawler Debug] 경고: 본문 콘텐츠 영역을 찾을 수 없습니다: {url}")
            full_content = ""
        logger.debug(f"--- [Crawler Debug] 추출된 본문 길이: {len(full_content)}. 내용(첫 100자): '{full_content[:100]}...'")
        extracted_keywords_str = extract_keywords_with_keybert(full_content, num_keywords=5, keyphrase_ngram_range=(1,2))
        logger.debug(f"--- [Crawler Debug] 최종 추출된 키워드: '{extracted_keywords_str}'")
        return full_content, extracted_keywords_str
    except requests.exceptions.RequestException as e:
        logger.error(f"--- [Crawler Error] 웹 크롤링 요청 오류 ({url}): {e}")
        return "", ""
    except Exception as e:
        logger.error(f"--- [Crawler Error] 웹 크롤링 중 파싱 오류 ({url}): {e}", exc_info=True)
        return "", ""

def fetch_and_store_news():
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    all_articles_count = 0
    new_articles_count = 0
    cur = None
    try:
        cur = mysql.connection.cursor()
        for query in SEARCH_QUERIES:
            params = {
                "query": query,
                "display": 100,
                "sort": "date"
            } 
            try:
                response = requests.get(NAVER_NEWS_API_URL, headers=headers, params=params)
                response.raise_for_status()
                news_data = response.json()
                for item in news_data.get('items', []):
                    all_articles_count += 1
                    link = item['link']
                    if "n.news.naver.com/mnews/article" not in link:
                        logger.info(f"[Main Debug] 네이버 뉴스 아티클 URL이 아님. 스킵: {link}")
                        continue
                    title = re.sub('<[^>]*>', '', item['title'])
                    description = re.sub('<[^>]*>', '', item['description'])
                    logger.info(f"\n[Main Debug] 뉴스 제목: {title[:50]}...")
                    logger.info(f"[Main Debug] API 요약(description) 길이: {len(description)}. 내용(첫 100자): '{description[:100]}...'")
                    if not description.strip():
                        logger.warning(f"[Main Debug] 경고: 이 뉴스의 API 요약이 비어있습니다. URL: {link}")
                    pub_date_str = item['pubDate']
                    pub_date_obj = datetime.strptime(pub_date_str[:-6], '%a, %d %b %Y %H:%M:%S')
                    cur.execute("SELECT id FROM articles WHERE url = %s", (link,))
                    existing_article = cur.fetchone()
                    if not existing_article:
                        logger.info(f"[Main Debug] 새 뉴스 발견: {title[:30]}...")
                        try:
                            full_content, extracted_keywords_str = get_naver_news_content_and_keywords(link)
                            cur.execute(
                                "INSERT INTO articles (title, summary, category, published_at, url, full_content) "
                                "VALUES (%s, %s, %s, %s, %s, %s)",
                                (title, description, query, pub_date_obj, link, full_content)
                            )
                            article_id = cur.lastrowid
                            logger.info(f"[Main Debug] Articles 테이블에 삽입 완료. article_id: {article_id}")
                            if extracted_keywords_str:
                                logger.info(f"[Main Debug] 키워드 추출 성공: '{extracted_keywords_str}'. DB 저장 시도.")
                                keyword_list = [k.strip() for k in extracted_keywords_str.split(',') if k.strip()]
                                for keyword_text in keyword_list:
                                    if not keyword_text:
                                        continue
                                    cur.execute("SELECT id FROM keywords WHERE keyword_text = %s", (keyword_text,))
                                    existing_keyword = cur.fetchone()
                                    if existing_keyword:
                                        keyword_id = existing_keyword[0]
                                        logger.debug(f"[Main Debug] 기존 키워드 사용: '{keyword_text}' (id: {keyword_id})")
                                    else:
                                        cur.execute("INSERT INTO keywords (keyword_text) VALUES (%s)", (keyword_text,))
                                        keyword_id = cur.lastrowid
                                        logger.debug(f"[Main Debug] 새 키워드 삽입: '{keyword_text}' (id: {keyword_id})")
                                    try:
                                        cur.execute("INSERT INTO article_keywords (article_id, keyword_id) VALUES (%s, %s)", (article_id, keyword_id))
                                        logger.debug(f"[Main Debug] article_keywords 연결 성공: article_id={article_id}, keyword_id={keyword_id}")
                                    except Exception as e_link:
                                        if "1062" not in str(e_link):
                                            logger.error(f"[Main Error] article_keywords 연결 중 오류 발생: {e_link}", exc_info=True)
                                        else:
                                            logger.debug(f"[Main Debug] article_keywords 연결 중복 스킵: article_id={article_id}, keyword_id={keyword_id}")
                            else:
                                logger.info(f"[Main Debug] 키워드 비어있음. 저장 스킵.")
                            mysql.connection.commit()
                            new_articles_count += 1
                            logger.info(f"[Main Debug] --- 최종 저장 및 커밋 완료: {title[:30]}... ---")
                        except Exception as e_insert:
                            if "1062" not in str(e_insert):
                                logger.error(f"[Main Error] 뉴스 저장 중 오류 발생: {e_insert}", exc_info=True)
                                mysql.connection.rollback()
                            else:
                                logger.info(f"[Main Debug] 중복 뉴스 스킵: {title[:30]}...")
                    else:
                        logger.info(f"[Main Debug] 이미 존재하는 뉴스 스킵: {title[:30]}...")
            except requests.exceptions.RequestException as e:
                logger.error(f"[Main Error] 네이버 API 요청 오류 ({query}): {e}", exc_info=True)
            except Exception as e:
                logger.error(f"[Main Error] 데이터 처리 중 오류 발생 ({query}): {e}", exc_info=True)
    finally:
        if cur:
            cur.close()
    logger.info(f"\n총 {all_articles_count}개의 뉴스 처리 시도, {new_articles_count}개의 새 뉴스 저장 완료.")

if __name__ == '__main__':
    with app.app_context():
        logger.info("뉴스 크롤링 및 DB 저장 시작...")
        fetch_and_store_news()
        logger.info("뉴스 크롤링 및 DB 저장 완료.")