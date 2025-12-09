import sys
import os
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QLabel, 
                             QMessageBox, QFrame)
from PyQt5.QtGui import QPixmap, QImage, QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import yt_dlp

# --- 작업 스레드 1: 영상 정보 조회 ---
class SearchThread(QThread):
    info_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            # 403 에러 방지를 위한 클라이언트 설정 (Android로 위장)
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                
                thumbnail_url = info.get('thumbnail')
                thumbnail_data = None
                if thumbnail_url:
                    response = requests.get(thumbnail_url)
                    thumbnail_data = response.content

                result = {
                    'title': info.get('title', '제목 없음'),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'thumbnail_data': thumbnail_data,
                    'url': self.url
                }
                self.info_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))

# --- 작업 스레드 2: 고화질 다운로드 (403 우회 + FFmpeg 병합) ---
class DownloadThread(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            # [핵심 설정]
            # 1. format: 비디오(최고화질 mp4) + 오디오(최고음질 m4a) 다운로드
            # 2. extractor_args: 'android'로 설정하여 403 Forbidden 우회
            # 3. merge_output_format: 최종 결과물을 mp4로 합침 (재생 호환성 확보)
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': '%(title)s.%(ext)s',
                'merge_output_format': 'mp4',
                
                # 403 에러 해결의 핵심 코드: 유튜브 앱인 척 위장
                'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
                
                'progress_hooks': [self.progress_hook],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            
            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('%','')
            self.progress_signal.emit(f"다운로드 중... {p}%")
        elif d['status'] == 'finished':
            self.progress_signal.emit("다운로드 완료! 파일 병합 중...")

# --- 메인 윈도우 UI (PyQt5) ---
class YoutubeDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.current_url = ""

    def initUI(self):
        self.setWindowTitle("YouTube Downloader (403 Fixed)")
        self.setGeometry(100, 100, 500, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # 1. URL 입력
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("유튜브 링크를 붙여넣으세요 (Ctrl+V)")
        self.search_btn = QPushButton("조회")
        self.search_btn.clicked.connect(self.start_search)
        
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.search_btn)
        layout.addLayout(input_layout)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # 2. 정보 표시
        self.thumbnail_label = QLabel("썸네일 미리보기")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setMinimumHeight(200)
        self.thumbnail_label.setStyleSheet("border: 1px solid #ccc; background-color: #f0f0f0;")
        layout.addWidget(self.thumbnail_label)

        self.title_label = QLabel("-")
        font = QFont("Arial", 12)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        info_layout = QHBoxLayout()
        self.view_label = QLabel("조회수: -")
        self.like_label = QLabel("좋아요: -")
        info_layout.addWidget(self.view_label)
        info_layout.addWidget(self.like_label)
        layout.addLayout(info_layout)

        layout.addStretch()

        # 3. 다운로드 버튼
        self.status_label = QLabel("대기 중")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.download_btn = QPushButton("고화질 다운로드 시작")
        btn_font = QFont("Arial", 11)
        btn_font.setBold(True)
        self.download_btn.setFont(btn_font)
        self.download_btn.setStyleSheet("background-color: #ff0000; color: white; padding: 10px;")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.start_download)
        layout.addWidget(self.download_btn)

    def start_search(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "경고", "유튜브 링크를 입력해주세요.")
            return

        self.status_label.setText("정보 조회 중...")
        self.search_btn.setEnabled(False)
        self.search_thread = SearchThread(url)
        self.search_thread.info_signal.connect(self.update_info)
        self.search_thread.error_signal.connect(self.search_error)
        self.search_thread.start()

    def update_info(self, info):
        self.current_url = info['url']
        self.title_label.setText(info['title'])
        
        views = f"{info['view_count']:,}" if info['view_count'] is not None else "비공개"
        likes = f"{info['like_count']:,}" if info['like_count'] is not None else "비공개"
        
        self.view_label.setText(f"조회수: {views}회")
        self.like_label.setText(f"좋아요: {likes}개")

        if info['thumbnail_data']:
            image = QImage.fromData(info['thumbnail_data'])
            pixmap = QPixmap.fromImage(image)
            scaled_pixmap = pixmap.scaled(self.thumbnail_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumbnail_label.setPixmap(scaled_pixmap)
        else:
            self.thumbnail_label.setText("썸네일 없음")

        self.status_label.setText("조회 완료")
        self.search_btn.setEnabled(True)
        self.download_btn.setEnabled(True)

    def search_error(self, err_msg):
        # 검색 단계에서도 403이 뜰 수 있으므로 안내
        if "HTTP Error 403" in err_msg:
             QMessageBox.critical(self, "접속 차단됨", "유튜브에서 접속을 차단했습니다.\n터미널에서 'pip install --upgrade yt-dlp'를 입력해 업데이트해주세요.")
        else:
            QMessageBox.critical(self, "에러", f"정보를 가져오는데 실패했습니다.\n{err_msg}")
        self.status_label.setText("에러 발생")
        self.search_btn.setEnabled(True)

    def start_download(self):
        if not self.current_url:
            return
        self.download_btn.setEnabled(False)
        self.url_input.setEnabled(False)
        self.search_btn.setEnabled(False)
        
        self.dw_thread = DownloadThread(self.current_url)
        self.dw_thread.progress_signal.connect(self.update_download_status)
        self.dw_thread.finished_signal.connect(self.download_finished)
        self.dw_thread.error_signal.connect(self.download_error)
        self.dw_thread.start()

    def update_download_status(self, msg):
        self.status_label.setText(msg)

    def download_finished(self):
        QMessageBox.information(self, "완료", "다운로드가 완료되었습니다!")
        self.status_label.setText("다운로드 완료")
        self.reset_ui_state()

    def download_error(self, err_msg):
        if "ffmpeg" in err_msg.lower():
             QMessageBox.critical(self, "FFmpeg 오류", "FFmpeg가 설치되지 않았거나 경로를 찾을 수 없습니다.\nffmpeg.exe를 이 프로그램과 같은 폴더에 넣어주세요.")
        elif "HTTP Error 403" in err_msg:
             QMessageBox.critical(self, "다운로드 차단됨", "유튜브 서버가 요청을 거부했습니다(403).\n프로그램을 종료 후 터미널에\n'pip install -U yt-dlp'를 입력하여 업데이트 후 다시 시도하세요.")
        else:
            QMessageBox.critical(self, "다운로드 실패", f"오류 내용:\n{err_msg}")
        
        self.status_label.setText("다운로드 실패")
        self.reset_ui_state()

    def reset_ui_state(self):
        self.download_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self.search_btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YoutubeDownloaderApp()
    window.show()
    sys.exit(app.exec_())