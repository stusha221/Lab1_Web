# tests/test_app.py

import io
import os
import sys
import pytest
from PIL import Image

# Добавляем корневую директорию в sys.path, чтобы импортировать app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, allowed_file


# Фикстура: тестовый клиент Flask
@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


# Фикстура: тестовое изображение в памяти
@pytest.fixture
def sample_image():
    img = Image.new('RGB', (100, 100), color='red')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes


# Вспомогательная функция: загружает главную и возвращает верный ответ на капчу
def _get_correct_captcha(client):
    client.get('/')
    with client.session_transaction() as sess:
        return sess['captcha_answer']


# Тест: главная страница открывается и содержит капчу
def test_index_page(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'Поворот изображения'.encode('utf-8') in response.data


# Тест: функция проверки расширений
def test_allowed_file():
    assert allowed_file('image.png') is True
    assert allowed_file('image.jpg') is True
    assert allowed_file('document.txt') is False
    assert allowed_file('no_extension') is False


# Тест: запрос без файла (но с верной капчей) выдаёт «Файл не выбран»
def test_rotate_no_file(client):
    correct_answer = _get_correct_captcha(client)

    response = client.post('/rotate', data={
        'captcha': correct_answer,
    }, follow_redirects=True)

    assert response.status_code == 200
    assert 'Файл не выбран'.encode('utf-8') in response.data


# Тест: неверная капча блокирует обработку
def test_rotate_invalid_captcha(client, sample_image):
    response = client.post('/rotate', data={
        'image': (sample_image, 'test.png'),
        'angle': '45',
        'captcha': 'wrong_answer',
    }, follow_redirects=True, content_type='multipart/form-data')

    assert 'Неверный ответ на капчу'.encode('utf-8') in response.data


# Тест: недопустимый формат файла
def test_rotate_invalid_extension(client):
    correct_answer = _get_correct_captcha(client)
    fake = io.BytesIO(b'not an image')

    response = client.post('/rotate', data={
        'image': (fake, 'document.txt'),
        'angle': '30',
        'captcha': correct_answer,
    }, follow_redirects=True, content_type='multipart/form-data')

    assert 'Недопустимый формат'.encode('utf-8') in response.data


# Тест: успешный поворот — рендерится страница результата с гистограммами
def test_rotate_success(client, sample_image):
    correct_answer = _get_correct_captcha(client)

    response = client.post('/rotate', data={
        'image': (sample_image, 'test.png'),
        'angle': '45',
        'direction': 'right',
        'captcha': correct_answer,
    }, follow_redirects=True, content_type='multipart/form-data')

    assert response.status_code == 200
    # Обе гистограммы встраиваются как data:image/png;base64
    assert response.data.count(b'data:image/png;base64,') == 2