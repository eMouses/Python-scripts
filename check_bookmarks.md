Проверка работоспособности ссылок или закладок браузера.
Поддерживает:
- Отслеживание редиректов (301, 302, 307, 308)
- Обход блокировок ботов (403/503/521)
- Детальную статистику

# Перед использованием установите необходимые пакеты:
pip install requests beautifulsoup4 fake-useragent cloudscraper

# Использование:

- Базовое использование
python check_bookmarks.py bookmarks.html

- С указанием выходного файла
python check_bookmarks.py bookmarks.html -o report.html

- С настройкой параметров
python check_bookmarks.py bookmarks.html -t 15 -w 10 -d 0.3

- Отключить обход блокировок
python check_bookmarks.py bookmarks.html --no-stealth

- Использовать прокси (создайте файл proxies.txt)
python check_bookmarks.py bookmarks.html --use-proxies

- Комбинированные настройки
python check_bookmarks.py bookmarks.html -t 20 -w 5 --use-proxies

# Параметры командной строки:

bookmarks_file - путь к файлу закладок (обязательный)

-o, --output - имя выходного HTML файла (по умолчанию: bookmarks_report.html)

-t, --timeout - таймаут запроса в секундах (по умолчанию: 10)

-w, --workers - количество параллельных потоков (по умолчанию: 5)

-d, --delay - задержка между запросами в секундах (по умолчанию: 0.5)
