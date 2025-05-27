from flask import Flask, request, render_template, session, redirect, url_for, flash
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
import os
from dotenv import load_dotenv
import MySQLdb

# .env 파일 로드
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key')

# MySQL 설정
app.config['MYSQL_HOST'] = os.getenv('DB_HOST')
app.config['MYSQL_USER'] = os.getenv('DB_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASS')
app.config['MYSQL_DB'] = os.getenv('DB_NAME')

mysql = MySQL(app)
bcrypt = Bcrypt(app)

# 홈 페이지
@app.route('/')
def home():
    if 'user_id' in session:
        return render_template('home.html', username=session['username'])
    return redirect(url_for('login'))

# 회원가입
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        
        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO users (email, username, password_hash) VALUES (%s, %s, %s)",
                (email, username, password_hash)
            )
            mysql.connection.commit()
            cur.close()
            flash('회원가입 성공! 로그인해주세요.', 'success')
            return redirect(url_for('login'))
        except MySQLdb.IntegrityError:
            flash('이메일이 이미 존재합니다.', 'error')
            return redirect(url_for('register'))
        except MySQLdb.OperationalError as e:
            flash(f'DB 연결 오류: {str(e)}', 'error')
            return redirect(url_for('register'))
    
    return render_template('register.html')

# 로그인
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT id, username, password_hash FROM users WHERE email = %s", [email])
            user = cur.fetchone()
            cur.close()
            
            if user and bcrypt.check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['username'] = user[1]
                flash('로그인 성공!', 'success')
                return redirect(url_for('home'))
            else:
                flash('이메일 또는 비밀번호가 잘못되었습니다.', 'error')
                return redirect(url_for('login'))
        except MySQLdb.OperationalError as e:
            flash(f'DB 연결 오류: {str(e)}', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')

# 로그아웃
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('로그아웃되었습니다.', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)