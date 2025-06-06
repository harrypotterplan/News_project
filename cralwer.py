import os
import requests
from dotenv import load_dotenv
from flask import Flask
from flask_mysqldb import MySQL
from datetime import datetime
import re
from bs4 import BeautifulSoup
import logging # logging 라이브러리 추가

# KeyBERT 관련 임포트
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer

# .env 파일 로드
load_dotenv()

app = Flask(__name__)

# MySQL 설정
app.config['MYSQL_HOST'] = os.getenv('DB_HOST')
app.config['MYSQL_USER'] = os.getenv('DB_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASS')
app.config['MYSQL_DB'] = os.getenv('DB_NAME')
mysql = MySQL(app)

# 네이버 API 설정
NAVER_CLIENT_ID = os.getenv('NAVER_CLIENT_ID')
NAVER_CLIENT_SECRET = os.getenv('NAVER_CLIENT_SECRET')
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

# 다양한 카테고리/키워드를 순환하며 검색
SEARCH_QUERIES = [
    "IT", "경제", "정치", "사회", "문화", "스포츠", "세계", "생활", "기술", "뉴스"
]

# --- 로깅 설정 ---
# 기존의 print 문을 logging으로 대체하기 위해 설정
logging.basicConfig(level=logging.INFO, # 기본 INFO 레벨, 디버그 메시지를 보려면 DEBUG로 변경
                    format='%(asctime)s - %(levelname)s - %(message)s')

# KeyBERT 모델 로드 (전역으로 한 번만 로드하여 재사용)
# 'jhgan/ko-sbert-nli'는 한국어 문장 임베딩에 널리 사용되는 모델이다.
# 처음 로드 시 모델 파일을 다운로드하므로 시간이 걸릴 수 있다.
logging.info("KeyBERT 모델 로딩 중... (처음 실행 시 시간이 걸릴 수 있습니다)")
try:
    kw_model = KeyBERT(model=SentenceTransformer('jhgan/ko-sbert-nli'))
    logging.info("KeyBERT 모델 로딩 완료.")
except Exception as e:
    logging.error(f"KeyBERT 모델 로딩 실패: {e}")
    kw_model = None # 모델 로딩 실패 시 None으로 설정

# 공통 불용어 목록 (필요에 따라 추가/수정)
COMMON_STOPWORDS = set([
    '대한', '우리', '이번', '지난', '동안', '이것', '그것', '저것', '다시', '관련', '위해', '통해', '등', '명', '것', '수', '점', '때', '곳', '바', '및', '위', '중', '이', '그', '지난해', '오늘', '내일', '이날', '해당', '현재', '가지', '이제', '말', '월', '년', '일', '고', '면', '좀', '개', '분', '뒤', '전', '기자'
])


def extract_keywords_with_keybert(text, num_keywords=5, keyphrase_ngram_range=(1,2)):
    """
    KeyBERT를 사용하여 텍스트에서 키워드를 추출.
    :param text: 기사 본문 텍스트
    :param num_keywords: 추출할 키워드 개수
    :param keyphrase_ngram_range: 추출할 키워드의 단어 길이 범위 (예: (1,1)은 단일 단어, (1,2)는 1~2개 단어 조합)
    :return: 콤마로 구분된 키워드 문자열
    """
    if not text:
        logging.debug("    [KeyBERT Debug] 입력 텍스트가 비어 있습니다. 키워드 추출 스킵.")
        return ""

    # 텍스트 전처리 (HTML 태그 제거, 특수문자 제거, 다중 공백 단일화)
    clean_text = re.sub(r'<[^>]+>|\s+', ' ', text).strip()
    clean_text = re.sub(r'[^\w\s]', '', clean_text) # 알파벳, 숫자, 한글, 공백 제외 문자 제거
    
    logging.debug(f"    [KeyBERT Debug] 전처리 후 텍스트 길이: {len(clean_text)}. 내용(첫 50자): '{clean_text[:50]}...'")
    if not clean_text:
        logging.debug("    [KeyBERT Debug] 전처리 후 텍스트가 비어 있습니다. 키워드 추출 스킵.")
        return ""

    # KeyBERT로 키워드 추출
    # kw_model은 이미 전역 변수로 로드되어 있음
    keywords_with_score = kw_model.extract_keywords(
        clean_text, 
        keyphrase_ngram_range=keyphrase_ngram_range, 
        stop_words=None, # KeyBERT의 stop_words는 기본적으로 영어 불용어이므로, None으로 설정하고 한국어 불용어는 후처리
        top_n=num_keywords * 2 # 원하는 개수보다 넉넉하게 추출 후 필터링
    )
    
    logging.debug(f"    [KeyBERT Debug] KeyBERT 1차 추출 결과(점수 포함): {keywords_with_score}")

    final_keywords = []
    for keyword, score in keywords_with_score:
        # 추출된 키워드(구문)를 단어 단위로 분리하여 불용어 검사 및 최소 길이 필터링
        is_stopword_phrase = False
        words_in_keyword = keyword.split()
        if not words_in_keyword: # 빈 문자열 키워드 방지
            continue

        for word in words_in_keyword:
            if word in COMMON_STOPWORDS or len(word) < 2: # 2글자 미만 단어도 필터링
                is_stopword_phrase = True
                break
        
        if not is_stopword_phrase:
            final_keywords.append(keyword)
            if len(final_keywords) >= num_keywords: # 원하는 개수만큼 채워지면 중단
                break
            
    logging.debug(f"    [KeyBERT Debug] 최종 필터링된 키워드: {final_keywords}")
            
    return ", ".join(final_keywords)


def get_naver_news_content_and_keywords(url):
    """
    네이버 뉴스 URL에서 본문과 키워드를 추출하는 함수 (KeyBERT 기반 키워드 추출)
    """
    global kw_model # 전역 KeyBERT 모델(kw_model)을 사용하기 위해 global 선언

    if kw_model is None:
        logging.error("[KeyBERT Error] KeyBERT 모델이 로드되지 않았습니다. 키워드 추출 불가.")
        return None, "키워드 추출 실패: KeyBERT 모델 로드 오류"

    logging.debug(f"\n--- [Crawler Debug] URL 처리 시작: {url}")
    try:
        # User-Agent를 좀 더 일반적인 브라우저 값으로 설정
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})
        response.raise_for_status() # HTTP 오류 발생 시 예외 발생
        soup = BeautifulSoup(response.text, 'html.parser')

        full_content = ""
        # 1. <article id="dic_area">를 먼저 시도 (가장 유력)
        content_div = soup.find('article', id='dic_area')

        # 2. 만약 id로 못 찾으면, class로 시도 (fallback)
        if not content_div:
            content_div = soup.find('article', class_='go_trans _article_content')

        # 3. 그래도 못 찾으면, div 태그의 id='dic_area'를 마지막으로 시도 (혹시 다른 뉴스 페이지에서 여전히 div일 경우)
        if not content_div:
            content_div = soup.find('div', id='dic_area')

        # 이전에 시도했던 다른 셀렉터들이 있다면 여기에 추가 (네이버 뉴스 페이지마다 구조가 다를 수 있음)
        # if not content_div:
        #     content_div = soup.find('div', class_='go_trans _article_content') # div 태그의 해당 클래스
        # if not content_div:
        #     content_div = soup.find('div', id='articleBodyContents') # div 태그의 다른 ID

        if content_div:
            # 본문 내 불필요한 태그 (예: 사진 설명 <em class="img_desc">) 제거 또는 필터링
            for img_desc in content_div.find_all('em', class_='img_desc'):
                img_desc.decompose() # 해당 태그와 내용 제거

            # <br> 태그를 줄바꿈으로 처리하여 본문 가독성 향상
            for br in content_div.find_all('br'):
                br.replace_with('\n') 

            full_content = content_div.get_text(strip=True)
            # 불필요한 스크립트 코드나 광고 문구 제거 (정규표현식 보강)
            full_content = re.sub(r'본문 내용 재생.*', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'^(.*?)\(function', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'flash 오류를 우회하기 위한 함수 추가\.[\s\S]*', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'// flash content end\.[\s\S]*', '', full_content, flags=re.DOTALL)
            full_content = re.sub(r'\[.+?\]', '', full_content) # [앵커] 같은 괄호 안 텍스트 제거
            full_content = re.sub(r'\(.+?\)기자', '', full_content) # (서울=연합뉴스) 기자 정보 제거
            full_content = re.sub(r'저작권자 ⓒ.+?\s', '', full_content) # 저작권 문구 제거
            full_content = re.sub(r'무단전재 및 재배포 금지\.?', '', full_content) # 무단전재 문구 제거
            full_content = re.sub(r'\S+@\S+\.\S+', '', full_content) # 이메일 주소 제거
            full_content = re.sub(r'\d{2,4}-\d{3,4}-\d{4}', '', full_content) # 전화번호 제거

            # 여러 줄바꿈을 하나로
            full_content = re.sub(r'\n\s*\n', '\n', full_content) 
            full_content = full_content.strip()

        else:
            logging.warning(f"--- [Crawler Debug] 경고: 본문 콘텐츠 영역을 찾을 수 없습니다: {url}")
            full_content = ""

        logging.debug(f"--- [Crawler Debug] 추출된 본문 길이: {len(full_content)}. 내용(첫 100자): '{full_content[:100]}...'")

        # 추출된 본문에서 KeyBERT 기반 키워드 추출
        # extract_keywords_with_keybert 함수는 이미 kw_model을 사용하도록 되어 있음
        extracted_keywords_str = extract_keywords_with_keybert(full_content, num_keywords=5, keyphrase_ngram_range=(1,2))

        logging.debug(f"--- [Crawler Debug] 최종 추출된 키워드: '{extracted_keywords_str}'")

        return full_content, extracted_keywords_str
        
    except requests.exceptions.RequestException as e:
        logging.error(f"--- [Crawler Error] 웹 크롤링 요청 오류 ({url}): {e}")
        return "", ""
    except Exception as e:
        logging.error(f"--- [Crawler Error] 웹 크롤링 중 파싱 오류 ({url}): {e}", exc_info=True) # exc_info=True로 스택 트레이스 출력
        return "", ""


def fetch_and_store_news():
    """
    네이버 뉴스 API를 통해 뉴스를 가져오고 DB에 저장하는 함수
    """
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    all_articles_count = 0
    new_articles_count = 0

    cur = None # cur 변수 초기화
    try:
        cur = mysql.connection.cursor()

        for query in SEARCH_QUERIES:
            params = {
                "query": query,  # 검색어
                "display": 30,   # 가져올 결과 개수 (최대 100) -> 테스트용으로 30으로 설정
                "sort": "date"   # 최신순 정렬
            }

            try:
                response = requests.get(NAVER_NEWS_API_URL, headers=headers, params=params)
                response.raise_for_status()
                news_data = response.json()
                
                for item in news_data.get('items', []):
                    all_articles_count += 1
                    link = item['link']

                    # 네이버 뉴스 기사 URL 패턴에 정확히 일치하는지 확인
                    # mnews/article 패턴을 포함해야 신뢰할 수 있는 본문 추출 가능성 높음
                    if "n.news.naver.com/mnews/article" not in link:
                        logging.info(f"[Main Debug] 네이버 뉴스 아티클 URL이 아님. 스킵: {link}")
                        continue
                    
                    # HTML 태그 제거 및 특수문자 디코딩
                    title = re.sub('<[^>]*>', '', item['title'])
                    description = re.sub('<[^>]*>', '', item['description']) 
                    
                    # --- [Main Debug] API에서 추출된 요약(description) 출력 ---
                    logging.info(f"\n[Main Debug] 뉴스 제목: {title[:50]}...")
                    logging.info(f"[Main Debug] API 요약(description) 길이: {len(description)}. 내용(첫 100자): '{description[:100]}...'")
                    if not description.strip():
                        logging.warning(f"[Main Debug] 경고: 이 뉴스의 API 요약이 비어있습니다. URL: {link}")
                    # --- [Main Debug] 출력 끝 ---

                    # 발행 시간 형식 변환
                    pub_date_str = item['pubDate']
                    pub_date_obj = datetime.strptime(pub_date_str[:-6], '%a, %d %b %Y %H:%M:%S')

                    # 이미 저장된 뉴스인지 확인 (api_article_id와 URL을 기준으로 중복 방지)
                    cur.execute("SELECT id FROM articles WHERE api_article_id = %s OR url = %s", (item['link'], item['link']))
                    existing_article = cur.fetchone()

                    if not existing_article:
                        logging.info(f"[Main Debug] 새 뉴스 발견: {title[:30]}...")
                        try:
                            # 기사 본문 및 키워드 추출 시도
                            full_content, extracted_keywords_str = get_naver_news_content_and_keywords(link)
                            
                            # articles 테이블에 기사 정보 저장
                            # 'full_content' 컬럼이 DB에 있다면 추가해도 됨
                            cur.execute(
                                "INSERT INTO articles (api_article_id, title, summary, category, published_at, url) VALUES (%s, %s, %s, %s, %s, %s)",
                                (item['link'], title, description, query, pub_date_obj, link)
                            )
                            article_id = cur.lastrowid # 새로 삽입된 기사의 ID를 가져옴
                            logging.info(f"[Main Debug] Articles 테이블에 삽입 완료. article_id: {article_id}")

                            # 키워드 테이블에 키워드 저장 및 article_keywords 테이블에 연결
                            if extracted_keywords_str: # 추출된 키워드가 있다면
                                logging.info(f"[Main Debug] 키워드 추출 성공: '{extracted_keywords_str}'. DB 저장 시도.")
                                keyword_list = [k.strip() for k in extracted_keywords_str.split(',') if k.strip()]
                                for keyword_text in keyword_list:
                                    if not keyword_text: # 빈 문자열 키워드 방지
                                        continue
                                    # 키워드가 이미 존재하는지 확인
                                    cur.execute("SELECT id FROM keywords WHERE keyword = %s", (keyword_text,))
                                    existing_keyword = cur.fetchone()

                                    if existing_keyword:
                                        keyword_id = existing_keyword[0]
                                        logging.debug(f"[Main Debug] 기존 키워드 사용: '{keyword_text}' (id: {keyword_id})")
                                    else:
                                        # 키워드가 없으면 새로 삽입
                                        cur.execute("INSERT INTO keywords (keyword) VALUES (%s)", (keyword_text,))
                                        keyword_id = cur.lastrowid
                                        logging.debug(f"[Main Debug] 새 키워드 삽입: '{keyword_text}' (id: {keyword_id})")

                                    # article_keywords 테이블에 연결 정보 저장 (중복 방지)
                                    try:
                                        cur.execute("INSERT INTO article_keywords (article_id, keyword_id) VALUES (%s, %s)", (article_id, keyword_id))
                                        logging.debug(f"[Main Debug] article_keywords 연결 성공: article_id={article_id}, keyword_id={keyword_id}")
                                    except Exception as e_link:
                                        # MySQL Error 1062는 중복 키 에러 (Unique Constraint violation)
                                        if "1062" not in str(e_link): 
                                            logging.error(f"[Main Error] article_keywords 연결 중 오류 발생 (article_id: {article_id}, keyword_id: {keyword_id}): {e_link}", exc_info=True)
                                        else:
                                            logging.debug(f"[Main Debug] article_keywords 연결 중복 스킵: article_id={article_id}, keyword_id={keyword_id}")

                            else:
                                logging.info(f"[Main Debug] extracted_keywords_str이 비어있어 키워드를 저장하지 않습니다.")

                            mysql.connection.commit()
                            new_articles_count += 1
                            logging.info(f"[Main Debug] --- 최종 저장 및 커밋 완료: {title[:30]}... ---") 
                        except Exception as e_insert:
                            # MySQL Error 1062는 중복 키 에러 (Unique Constraint violation)
                            if "1062" not in str(e_insert):
                                logging.error(f"[Main Error] 뉴스 또는 키워드 저장 중 오류 발생 ({link}): {e_insert}", exc_info=True)
                                mysql.connection.rollback() # 오류 발생 시 롤백
                            else:
                                logging.info(f"[Main Debug] 중복 뉴스 스킵: {title[:30]}...") 
                    else:
                        logging.info(f"[Main Debug] 이미 존재하는 뉴스 스킵: {title[:30]}...")
                
            except requests.exceptions.RequestException as e:
                logging.error(f"[Main Error] 네이버 API 요청 오류 ({query}): {e}", exc_info=True)
            except Exception as e:
                logging.error(f"[Main Error] 데이터 처리 중 오류 발생 ({query}): {e}", exc_info=True)
        
    finally:
        if cur:
            cur.close() 
    
    logging.info(f"\n총 {all_articles_count}개의 뉴스 처리 시도, {new_articles_count}개의 새 뉴스 저장 및 키워드 연결 완료.")


if __name__ == '__main__':
    with app.app_context(): # Flask 앱 컨텍스트 내에서 DB 작업 수행
        logging.info("뉴스 크롤링 및 DB 저장 시작...")
        fetch_and_store_news()
        logging.info("뉴스 크롤링 및 DB 저장 완료.")