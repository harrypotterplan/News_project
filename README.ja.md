# 📰 AI News Master

ユーザーの**検索履歴・閲覧ログ・いいね/よくないねフィードバック**を分析し、**パーソナライズされたニュース**を推薦するAIニュース推薦Webサービスです。

Naverニュースをリアルタイムで収集し、**KeyBERT**でキーワードを自動抽出、**BPR（Bayesian Personalized Ranking）** モデルとキーワードベースを組み合わせた**ハイブリッド推薦**を提供します。

<br>

## 📌 プロジェクト概要

| 項目 | 内容 |
|------|------|
| **開発期間** | 2025.03 ～ 2025.06（4ヶ月） |
| **チーム構成** | 3名（BE & AI 統括、FE、書類・論文担当） |
| **受賞** | 2025 韓国デジタルコンテンツ学会 銅賞 🥉 |

**主な特徴**
- リアルタイムニュースクローリング + KeyBERTによる自動キーワード抽出
- ユーザー行動ベースのパーソナライズ推薦（**BPR + キーワードのハイブリッド**）
- 推薦モデルの性能評価（Precision, Recall, NDCG など）

<br>

## 🛠 技術スタック

| 区分 | 使用技術 |
|------|----------|
| **言語** | Python 3.10 |
| **フレームワーク** | Flask |
| **データベース** | MySQL 8.0 |
| **クローリング** | BeautifulSoup4, requests, Naver News API |
| **キーワード抽出** | KeyBERT + SentenceTransformer (`jhgan/ko-sbert-nli`) |
| **推薦モデル** | **BPR（Bayesian Personalized Ranking）** |
| **その他** | SQLAlchemy, pandas, numpy, joblib, python-dotenv |

<br>

## 📁 プロジェクト構成

```
AI-News-Master/
├── app.py                      # Flask メインサーバー
├── BPR_model.py                # BPR モデル学習
├── crawler.py                  # ニュースクローリング + キーワード抽出
├── evaluate_bpr_model.py       # BPR モデル評価
├── evaluate_keyword_model.py   # キーワードベース評価
├── model_data/                 # 学習済みモデルの保存
├── templates/                  # HTML テンプレート
├── .env                        # 環境変数
└── requirements.txt
```

<br>

## 🚀 インストールおよび実行方法

### 1. リポジトリのクローン

```bash
git clone https://github.com/harrypotterplan/News_project.git
cd News_project
```

### 2. 仮想環境の作成と有効化

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac / Linux
```

### 3. 必要なパッケージのインストール

```bash
pip install -r requirements.txt
```

### 4. 環境変数の設定（`.env`）

プロジェクトのルートに `.env` ファイルを作成し、以下の内容を入力してください：

```env
DB_HOST=localhost
DB_USER=root
DB_PASS=your_password
DB_NAME=AI_master
DB_PORT=3306
SECRET_KEY=your_secret_key
```

### 5. データベースの設定

1. MySQL で `AI_master` データベースを作成
2. `init_db.sql` を実行してテーブルを作成

### 6. BPR モデルの学習（初回のみ実行）

```bash
python BPR_model.py
```

### 7. Flask サーバーの起動

```bash
python app.py
```

> サーバーは `http://localhost:5000` で起動します。

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

## 🎯 使い方

1. 会員登録後ログイン
2. 検索窓に興味のあるキーワードを入力
3. ホーム画面でパーソナライズされた推薦ニュースを確認
4. 記事詳細ページでいいね/よくないねフィードバックを送信

<br>

## 💡 開発を通じて学んだこと

推薦モデルの選定にあたり、複数のアルゴリズムを実際に比較・検証しました。

- 当初は **LightFM** と **SVD（Surprise）** を試みましたが、サービス初期はユーザーの相互作用データが不足しており（**コールドスタート問題**）、評価値予測ベースのモデルでは性能が安定しませんでした。
- 明示的な評価値ではなく**暗黙的フィードバック（閲覧・いいね）** により適した **BPR（Bayesian Personalized Ranking）** を最終的に採用し、ランキング品質（NDCG など）を改善しました。
- 単一モデルの限界を補うため、**キーワードベース推薦と組み合わせたハイブリッド構成**を設計し、コールドスタート状況を緩和しました。

> モデル自体の精度だけでなく、**サービスのデータ特性に合ったアルゴリズムを選択する判断力**の重要性を体得したプロジェクトでした。
