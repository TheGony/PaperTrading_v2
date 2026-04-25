import logging
import os
from logging.handlers import TimedRotatingFileHandler

_logger = None

def get_logger():
    global _logger
    if _logger:
        return _logger

    os.makedirs('logs', exist_ok=True)

    _logger = logging.getLogger('papertrading')
    _logger.setLevel(logging.DEBUG)

    # 날짜별 로그 파일 (logs/2026-04-20.log)
    file_handler = TimedRotatingFileHandler(
        'logs/trading.log',
        when='midnight',
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.suffix = '%Y-%m-%d'
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    ))

    # 콘솔 출력도 유지
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    ))

    _logger.addHandler(file_handler)
    _logger.addHandler(console_handler)

    return _logger
