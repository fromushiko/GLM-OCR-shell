import sys
import os
import subprocess
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QFileDialog, QTextEdit, QListWidget, QMessageBox,
                            QGroupBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
GLM_API_KEY_FILE = os.path.join(CONFIG_DIR, "glm_api_key.txt")

def load_saved_api_key():
    if os.path.exists(GLM_API_KEY_FILE):
        with open(GLM_API_KEY_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""

def save_api_key(api_key):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(GLM_API_KEY_FILE, 'w', encoding='utf-8') as f:
        f.write(api_key)

class OCRThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, pdf_paths, api_key):
        super().__init__()
        self.pdf_paths = pdf_paths if isinstance(pdf_paths, list) else [pdf_paths]
        self.api_key = api_key
    
    def run(self):
        total = len(self.pdf_paths)
        for i, pdf_path in enumerate(self.pdf_paths):
            self.progress_signal.emit(i + 1, total)
            self.log_signal.emit(f"\n{'='*50}")
            self.log_signal.emit(f"处理第 {i+1}/{total} 个文件: {os.path.basename(pdf_path)}")
            self.log_signal.emit(f"{'='*50}")
            
            try:
                cmd = [sys.executable, 'ocr_core.py', pdf_path, '100', self.api_key]
                self.log_signal.emit(f"执行命令: {' '.join(cmd)}")
                
                result = subprocess.run(cmd, cwd=os.path.dirname(__file__), 
                                       capture_output=True, text=True)
                
                if result.stdout:
                    self.log_signal.emit(result.stdout)
                if result.stderr:
                    self.log_signal.emit(f"错误: {result.stderr}")
                
            except Exception as e:
                self.log_signal.emit(f"处理失败: {str(e)}")
        
        self.finished_signal.emit(True, f"批量处理完成! 共处理 {total} 个文件")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GLM OCR Shell")
        self.setMinimumSize(800, 600)
        self.ocr_thread = None
        self.setup_ui()
    
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        api_group = QGroupBox("API 配置")
        api_layout = QVBoxLayout()
        
        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("API Key:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("请输入智谱AI API Key")
        self.api_key_input.setText(load_saved_api_key())
        api_key_layout.addWidget(self.api_key_input)
        api_layout.addLayout(api_key_layout)
        
        api_hint = QLabel("获取API Key: https://open.bigmodel.cn/")
        api_hint.setStyleSheet("color: #666; font-size: 12px;")
        api_layout.addWidget(api_hint)
        
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
        
        file_group = QGroupBox("文件选择")
        file_layout = QVBoxLayout()
        
        file_select_layout = QHBoxLayout()
        self.file_path_input = QLineEdit()
        self.file_path_input.setPlaceholderText("选择PDF文件...")
        self.file_path_input.setReadOnly(True)
        file_select_layout.addWidget(self.file_path_input)
        
        self.select_file_btn = QPushButton("浏览...")
        self.select_file_btn.clicked.connect(self.select_file)
        file_select_layout.addWidget(self.select_file_btn)
        
        file_layout.addLayout(file_select_layout)
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        self.start_btn = QPushButton("开始识别")
        self.start_btn.setMinimumHeight(50)
        self.start_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.start_btn.clicked.connect(self.start_ocr)
        layout.addWidget(self.start_btn)
        
        paddle_layout = QHBoxLayout()
        self.paddle_btn = QPushButton("使用 PaddleOCR 云端服务")
        self.paddle_btn.clicked.connect(self.open_paddleocr)
        paddle_layout.addStretch()
        paddle_layout.addWidget(self.paddle_btn)
        layout.addLayout(paddle_layout)
        
        log_group = QGroupBox("日志输出")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        results_group = QGroupBox("输出文件")
        results_layout = QVBoxLayout()
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.open_file)
        results_layout.addWidget(self.results_list)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        self.refresh_files()
    
    def select_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择PDF文件", "", "PDF文件 (*.pdf)"
        )
        if file_paths:
            self.file_path_input.setText(f"已选择 {len(file_paths)} 个文件")
            self.file_path_input.setToolTip("\n".join(file_paths))
    
    def open_paddleocr(self):
        import webbrowser
        webbrowser.open("https://aistudio.baidu.com/paddleocr/task")
    
    def start_ocr(self):
        api_key = self.api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "警告", "请输入智谱AI API Key!")
            return
        
        save_api_key(api_key)
        
        file_path = self.file_path_input.toolTip().strip()
        if not file_path:
            QMessageBox.warning(self, "警告", "请选择PDF文件!")
            return
        
        pdf_paths = file_path.split("\n")
        pdf_paths = [p for p in pdf_paths if p and os.path.exists(p)]
        
        if not pdf_paths:
            QMessageBox.warning(self, "警告", "请选择有效的PDF文件!")
            return
        
        self.start_btn.setEnabled(False)
        self.start_btn.setText("处理中...")
        self.log_text.append(f"开始批量处理: {len(pdf_paths)} 个文件")
        
        self.ocr_thread = OCRThread(pdf_paths, api_key)
        self.ocr_thread.log_signal.connect(self.append_log)
        self.ocr_thread.progress_signal.connect(self.update_progress)
        self.ocr_thread.finished_signal.connect(self.ocr_finished)
        self.ocr_thread.start()
    
    def update_progress(self, current, total):
        self.start_btn.setText(f"处理中... ({current}/{total})")
    
    def append_log(self, text):
        self.log_text.append(text)
    
    def ocr_finished(self, success, message):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("开始识别")
        
        if success:
            QMessageBox.information(self, "完成", message)
            self.refresh_files()
        else:
            QMessageBox.critical(self, "错误", message)
    
    def refresh_files(self):
        output_dir = os.path.join(os.path.dirname(__file__), "output")
        self.results_list.clear()
        
        if os.path.exists(output_dir):
            for f in os.listdir(output_dir):
                if f.endswith(('.md', '.docx')):
                    self.results_list.addItem(f)
    
    def open_file(self, item):
        filename = item.text()
        filepath = os.path.join(os.path.dirname(__file__), "output", filename)
        if os.path.exists(filepath):
            os.startfile(filepath)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
