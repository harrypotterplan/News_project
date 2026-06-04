# 📰 AI News Master

사용자의 **검색 기록 · 조회 로그 · 좋아요/싫어요 피드백**을 분석하여 **개인화된 뉴스**를 추천하는 AI 기반 뉴스 추천 웹 서비스입니다.

Naver 뉴스를 실시간으로 수집하고, **KeyBERT**로 키워드를 추출하며, **BPR(Bayesian Personalized Ranking)** 모델과 키워드 기반을 결합한 **하이브리드 추천**을 제공합니다.

<br>

## 📌 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **개발 기간** | 2025.03 ~ 2025.06 (4개월) |
| **팀 구성** | 3명 (BE & AI 총괄, FE, 서류·논문 담당) |
| **수상** | 2025 한국디지털콘텐츠학회 동상 🥉 |

**주요 특징**
- 실시간 뉴스 크롤링 + KeyBERT 자동 키워드 추출
- 사용자 행동 기반 개인화 추천 (**BPR + Keyword 하이브리드**)
- 추천 모델 성능 평가 (Precision, Recall, NDCG 등)

<br>

## 🛠 기술 스택

| 구분 | 사용 기술 |
|------|-----------|
| **Language** | Python 3.10 |
| **Framework** | Flask |
| **Database** | MySQL 8.0 |
| **크롤링** | BeautifulSoup4, requests, Naver News API |
| **키워드 추출** | KeyBERT + SentenceTransformer (`jhgan/ko-sbert-nli`) |
| **추천 모델** | **BPR (Bayesian Personalized Ranking)** |
| **기타** | SQLAlchemy, pandas, numpy, joblib, python-dotenv |

<br>

## 📁 프로젝트 구조

```
AI-News-Master/
├── app.py                      # Flask 메인 서버
├── BPR_model.py                # BPR 모델 학습
├── crawler.py                  # 뉴스 크롤링 + 키워드 추출
├── evaluate_bpr_model.py       # BPR 모델 평가
├── evaluate_keyword_model.py   # 키워드 기반 평가
├── model_data/                 # 학습된 모델 저장
├── templates/                  # HTML 템플릿
├── .env                        # 환경 변수
└── requirements.txt
```

<br>

## 🚀 설치 및 실행 방법

### 1. 저장소 클론

```bash
git clone https://github.com/harrypotterplan/News_project.git
cd News_project
```

### 2. 가상환경 생성 및 활성화

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac / Linux
```

### 3. 필요한 패키지 설치

```bash
pip install -r requirements.txt
```

### 4. 환경 변수 설정 (`.env`)

프로젝트 루트에 `.env` 파일을 만들고 아래 내용을 입력하세요:

```env
DB_HOST=localhost
DB_USER=root
DB_PASS=your_password
DB_NAME=AI_master
DB_PORT=3306
SECRET_KEY=your_secret_key
```

### 5. 데이터베이스 설정

1. MySQL에서 `AI_master` 데이터베이스 생성
2. `init_db.sql` 파일 실행하여 테이블 생성

### 6. BPR 모델 학습 (최초 1회 실행)

```bash
python BPR_model.py
```

### 7. Flask 서버 실행

```bash
python app.py
```

> 서버가 `http://localhost:5000` 에서 실행됩니다.

<br>

## 📋 requirements.txt

```txt
Flask==2.3.3
Flask-MySQLdb==1.0.1
Flask-Bcrypt==1.0.1
SQLAlchemy==2.0.23
pandas==2.1.4
numpy==1.26.2
beautifulsoup4==4.12.2
requests==2.31.0
keybert==0.8.4
sentence-transformers==2.2.2
python-dotenv==1.0.0
joblib==1.3.2
```

<br>

## 🎯 사용 방법

1. 회원가입 후 로그인
2. 검색창에 관심 키워드 입력
3. 홈 화면에서 개인화된 추천 뉴스 확인
4. 기사 상세 페이지에서 좋아요/싫어요 피드백 제공

<br>

## 💡 개발 과정에서 배운 점

추천 모델 선정 과정에서 여러 알고리즘을 직접 비교·검증했습니다.

- 초기에는 **LightFM**과 **SVD(Surprise)** 를 시도했으나, 초기 서비스 특성상 **상호작용 데이터가 부족(cold-start)** 하여 평점 예측 기반 모델의 성능이 안정적이지 않았습니다.
- 명시적 평점이 아닌 **암묵적 피드백(조회·좋아요)** 에 더 적합한 **BPR(Bayesian Personalized Ranking)** 을 최종 채택하여, 랭킹 품질(NDCG 등) 지표를 개선했습니다.
- 단일 모델의 한계를 보완하기 위해 **키워드 기반 추천과 결합한 하이브리드 구조**로 콜드스타트 상황을 완화했습니다.

> 모델 자체의 정확도뿐 아니라, **서비스 데이터 특성에 맞는 알고리즘을 선택하는 판단력**의 중요성을 체득했습니다.
