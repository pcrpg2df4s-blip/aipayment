import os
import zipfile
import datetime
import requests
from dotenv import load_dotenv

# 1. Рабочая директория бота
WORK_DIR = '/home/banana/'
BACKUP_DIR = os.path.join(WORK_DIR, 'backups')
ENV_PATH = os.path.join(WORK_DIR, '.env')

# Папки, которые нужно исключить из бэкапа
EXCLUDE_DIRS = {'venv', '__pycache__', '.git', 'backups'}

def create_archive() -> tuple[str, str]:
    """Создает zip архив рабочей директории с исключением тяжелых и ненужных папок."""
    # 2. Создаем папку backups, если её нет
    os.makedirs(BACKUP_DIR, exist_ok=True)
        
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    backup_filename = f"backup_{date_str}.zip"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    
    print(f"Создание архива: {backup_path}")
    
    # 3. Архивация
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(WORK_DIR):
            # Модифицируем список dirs in-place, чтобы os.walk не заходил в исключенные папки
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for file in files:
                file_path = os.path.join(root, file)
                # Вычисляем относительный путь для сохранения внутри архива
                arcname = os.path.relpath(file_path, WORK_DIR)
                zipf.write(file_path, arcname)
                
    return backup_path, date_str

def rotate_backups(max_backups: int = 7):
    """Удаляет старые бэкапы, оставляя только max_backups самых свежих."""
    # 4. Ротация (очистка)
    backups = []
    
    if not os.path.exists(BACKUP_DIR):
        return

    for f in os.listdir(BACKUP_DIR):
        if f.startswith('backup_') and f.endswith('.zip'):
            full_path = os.path.join(BACKUP_DIR, f)
            backups.append(full_path)
            
    # Сортируем файлы по времени изменения (от старых к новым)
    backups.sort(key=os.path.getmtime)
    
    # Удаляем самые старые файлы, пока их количество больше max_backups
    while len(backups) > max_backups:
        oldest_backup = backups.pop(0)
        try:
            os.remove(oldest_backup)
            print(f"Удален старый бэкап: {oldest_backup}")
        except Exception as e:
            print(f"Ошибка при удалении {oldest_backup}: {e}")

def send_to_telegram(backup_path: str, date_str: str):
    """Отправляет созданный архив в указанный Telegram-канал."""
    # 5. Отправка в Telegram
    load_dotenv(ENV_PATH)
    
    bot_token = os.getenv('BOT_TOKEN')
    channel_id = os.getenv('BACKUP_CHANNEL_ID')
    
    if not bot_token or not channel_id:
        print("Ошибка: BOT_TOKEN или BACKUP_CHANNEL_ID не найдены в .env!")
        return
        
    # Вычисляем размер файла в мегабайтах
    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    size_mb_rounded = round(size_mb, 2)
    
    caption = f"📦 Бэкап от {date_str}. Размер: {size_mb_rounded} МБ."
    
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    
    print(f"Отправка архива в Telegram ({size_mb_rounded} МБ)...")
    
    try:
        with open(backup_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': channel_id, 'caption': caption}
            response = requests.post(url, data=data, files=files)
            
        if response.status_code == 200:
            print("✅ Бэкап успешно отправлен в Telegram.")
        else:
            print(f"❌ Ошибка отправки в Telegram: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Системная ошибка при отправке в Telegram: {e}")

def main():
    print(f"=== Запуск бэкапа: {datetime.datetime.now()} ===")
    try:
        backup_path, date_str = create_archive()
        rotate_backups(max_backups=7)
        send_to_telegram(backup_path, date_str)
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    print("=== Завершение бэкапа ===\n")

if __name__ == "__main__":
    main()
