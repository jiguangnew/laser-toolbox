@echo off
cd /d "%~dp0"
set PYTHONPATH=%CD%\vendor;%PYTHONPATH%
set MPLBACKEND=Agg
python -c "import ezdxf, matplotlib" >nul 2>nul
if errorlevel 1 (
  echo ���ڰ�װ�Ͽڴ���������
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo ������װʧ�ܡ����� Python ����������ԡ�
    pause
    exit /b 1
  )
)
python app.py
pause

