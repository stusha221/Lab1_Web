import os
import io
import base64
import random
import uuid
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import (Flask, render_template, request, session,
                   redirect, url_for, flash)
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

# Пути и настройки
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'}

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-me-to-a-random-secret-key'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def allowed_file(filename):
    # Проверка расширения файла
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS)


def new_captcha():
    # Генерация примера для капчи
    a, b = random.randint(2, 9), random.randint(2, 9)
    if random.random() < 0.5:
        question, answer = f'{a} + {b}', a + b
    else:
        if a < b:
            a, b = b, a
        question, answer = f'{a} − {b}', a - b
    session['captcha_question'] = question
    session['captcha_answer'] = str(answer)


def check_captcha(user_answer):
    # Проверка ответа на капчу
    expected = session.pop('captcha_answer', None)
    session.pop('captcha_question', None)
    return expected is not None and user_answer.strip() == expected


def get_font(size):
    # Подбор системного шрифта, иначе — встроенный
    for path in ('DejaVuSans.ttf', 'arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def add_datetime_stamp(image):
    # Наложение даты и времени через полупрозрачную маску (RGBA-слой)
    stamp_text = datetime.now().strftime('%d.%m.%Y %H:%M:%S')

    base = image.convert('RGBA')

    # Прозрачный слой-маска того же размера
    overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = get_font(size=max(16, base.width // 30))
    bbox = draw.textbbox((0, 0), stamp_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Положение в правом нижнем углу
    pad = 12
    margin = 16
    x1 = base.width - tw - pad * 2 - margin
    y1 = base.height - th - pad * 2 - margin
    x2 = base.width - margin
    y2 = base.height - margin

    # Полупрозрачная подложка и белый текст
    draw.rectangle([x1, y1, x2, y2], fill=(0, 0, 0, 160))
    draw.text((x1 + pad, y1 + pad - bbox[1]), stamp_text,
              font=font, fill=(255, 255, 255, 230))

    # Совмещение маски с изображением
    result = Image.alpha_composite(base, overlay)
    return result.convert('RGB'), stamp_text


def build_histogram(image, title):
    # Построение графика распределения цветов по каналам R, G, B
    arr = np.asarray(image.convert('RGB'))

    fig, ax = plt.subplots(figsize=(6.6, 3.3))
    for idx, (color, label) in enumerate(
            zip(('red', 'green', 'blue'),
                ('R — красный', 'G — зелёный', 'B — синий'))):
        hist = np.bincount(arr[:, :, idx].ravel(), minlength=256)
        ax.plot(np.arange(256), hist, color=color, linewidth=1.0, label=label)

    ax.set_title(title, fontsize=11)
    ax.set_xlabel('Интенсивность цвета (0–255)')
    ax.set_ylabel('Количество пикселей')
    ax.set_xlim(0, 255)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()

    # Сохранение графика в base64 для вставки в HTML
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return 'data:image/png;base64,' + base64.b64encode(buf.read()).decode('ascii')


def parse_angle(raw):
    # Проверка корректности угла
    try:
        value = float(raw.replace(',', '.').strip())
    except (ValueError, AttributeError):
        raise ValueError('Угол поворота должен быть числом.')
    if value < 0:
        raise ValueError('Угол должен быть неотрицательным.')
    if value > 360:
        raise ValueError('Угол должен быть от 0 до 360 градусов.')
    return value


@app.route('/')
def index():
    # Главная страница с формой
    if 'captcha_question' not in session:
        new_captcha()
    return render_template('index.html',
                           captcha_question=session['captcha_question'])


@app.route('/rotate', methods=['POST'])
def rotate():
    # Обработка формы и поворот изображения

    # Проверка капчи
    if not check_captcha(request.form.get('captcha', '')):
        flash('Неверный ответ на капчу. Попробуйте ещё раз.')
        return redirect(url_for('index'))

    # Проверка файла
    file = request.files.get('image')
    if not file or file.filename == '':
        flash('Файл не выбран.')
        return redirect(url_for('index'))
    if not allowed_file(file.filename):
        flash('Недопустимый формат. Разрешены: ' +
              ', '.join(sorted(ALLOWED_EXTENSIONS)).upper())
        return redirect(url_for('index'))

    # Проверка угла
    try:
        angle = parse_angle(request.form.get('angle', '0'))
    except ValueError as e:
        flash(str(e))
        return redirect(url_for('index'))

    # Направление поворота
    direction = request.form.get('direction', 'right')
    if direction not in ('right', 'left'):
        direction = 'right'

    # Вправо — по часовой, влево — против часовой
    signed_angle = -angle if direction == 'right' else angle

    # Флажок «добавить дату и время»
    add_stamp = request.form.get('add_stamp') == 'on'

    # Сохранение загруженного файла
    ext = file.filename.rsplit('.', 1)[1].lower()
    token = uuid.uuid4().hex
    src_name = f'{token}_src.{ext}'
    src_path = os.path.join(app.config['UPLOAD_FOLDER'], src_name)
    file.save(src_path)

    # Открытие изображения
    try:
        original = Image.open(src_path)
        original.load()
    except (UnidentifiedImageError, OSError):
        os.remove(src_path)
        flash('Не удалось распознать изображение.')
        return redirect(url_for('index'))

    original = original.convert('RGB')

    # Поворот изображения
    rotated = original.rotate(signed_angle,
                              resample=Image.BICUBIC,
                              expand=True,
                              fillcolor=(255, 255, 255))

    # Наложение даты и времени по маске (если отмечено)
    stamp_text = None
    if add_stamp:
        rotated, stamp_text = add_datetime_stamp(rotated)

    # Сохранение результата
    res_name = f'{token}_rot.png'
    res_path = os.path.join(app.config['UPLOAD_FOLDER'], res_name)
    rotated.save(res_path, format='PNG')

    # Построение гистограмм
    direction_word = 'вправо' if direction == 'right' else 'влево'
    hist_src = build_histogram(original, 'Исходное изображение')
    hist_res = build_histogram(
        rotated, f'Изображение, повёрнутое {direction_word} на {angle:g}°')

    return render_template(
        'result.html',
        angle=angle,
        direction_word=direction_word,
        stamp_text=stamp_text,
        src_url=url_for('static', filename=f'uploads/{src_name}'),
        res_url=url_for('static', filename=f'uploads/{res_name}'),
        hist_src=hist_src,
        hist_res=hist_res,
        src_size=f'{original.width}×{original.height}',
        res_size=f'{rotated.width}×{rotated.height}',
    )


if __name__ == '__main__':
    app.run(debug=True)