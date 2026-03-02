@echo off
chcp 65001 >nul
pip install PyQt6 -q
start "" python "%~dp0gui.py"
