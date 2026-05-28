#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Скрипт для проверки доступности ссылок из закладок Firefox
Поддерживает:
- Отслеживание редиректов (301, 302, 307, 308)
- Обход блокировок ботов (403/503/521)
- Детальную статистику
"""

import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, urljoin
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import random
from fake_useragent import UserAgent
import cloudscraper
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class BookmarkChecker:
    def __init__(self, timeout=10, max_workers=5, delay=0.5, use_stealth=True, max_redirects=10):
        self.timeout = timeout
        self.max_workers = max_workers
        self.delay = delay
        self.use_stealth = use_stealth
        self.max_redirects = max_redirects
        
        try:
            self.ua = UserAgent()
        except:
            self.ua = None
            
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
        
        self.session = self._create_session()
        
        if use_stealth:
            try:
                self.scraper = cloudscraper.create_scraper(
                    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                    delay=10
                )
                print("✅ CloudScraper инициализирован")
            except:
                self.scraper = None
                print("⚠️ CloudScraper не доступен")
        else:
            self.scraper = None
            
        self.results = []
        
    def _create_session(self):
        session = requests.Session()
        # Разрешаем автоматическое следование редиректам, но с ограничением
        session.max_redirects = self.max_redirects
        retry_strategy = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def _get_random_user_agent(self):
        if self.ua:
            try:
                return self.ua.random
            except:
                return random.choice(self.user_agents)
        return random.choice(self.user_agents)
    
    def _get_stealth_headers(self, url):
        parsed = urlparse(url)
        return {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Referer': f"{parsed.scheme}://{parsed.netloc}/",
            'DNT': '1',
        }
    
    def _is_bot_protection(self, response):
        """Проверяет, является ли ответ страницей защиты от ботов"""
        if not hasattr(response, 'text'):
            return False
        text = response.text.lower()
        protection_signatures = [
            'checking your browser', 'ddos protection', 'cloudflare',
            'access denied', 'bot protection', 'captcha', 'just a moment',
            'verify you are human', 'security check', 'attention required'
        ]
        return any(signature in text for signature in protection_signatures)
    
    def _extract_redirect_chain(self, response, history):
        """Извлекает цепочку редиректов из истории запроса"""
        redirect_chain = []
        
        # Обрабатываем историю редиректов
        for resp in history:
            redirect_chain.append({
                'url': resp.url,
                'status_code': resp.status_code,
                'location': resp.headers.get('Location', '')
            })
        
        # Добавляем финальный URL
        final_url = response.url if hasattr(response, 'url') else None
        
        return redirect_chain, final_url
    
    def parse_bookmarks_html(self, html_file):
        print(f"📖 Чтение файла закладок: {html_file}")
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'html.parser')
        bookmarks = []
        
        for link in soup.find_all('a'):
            url = link.get('href')
            title = link.get_text(strip=True)
            add_date = link.get('add_date')
            
            if url and url.startswith(('http://', 'https://')):
                bookmarks.append({
                    'url': url,
                    'title': title if title else url,
                    'add_date': datetime.fromtimestamp(int(add_date)).strftime('%Y-%m-%d %H:%M:%S') if add_date else 'Unknown'
                })
        
        print(f"✅ Найдено закладок: {len(bookmarks)}")
        return bookmarks
    
    def _try_bypass(self, url):
        """Попытка обойти защиту"""
        try:
            if self.scraper:
                start_time = time.time()
                response = self.scraper.get(url, timeout=self.timeout)
                if response.status_code < 400:
                    return {
                        'success': True,
                        'status_code': response.status_code,
                        'response_time': round((time.time() - start_time) * 1000),
                        'response': response,
                        'history': response.history
                    }
            return None
        except:
            return None
    
    def check_url(self, bookmark):
        """Проверка одной ссылки с отслеживанием редиректов"""
        url = bookmark['url']
        title = bookmark['title']
        
        # Используем сессию CloudScraper если включен stealth
        if self.use_stealth and self.scraper:
            session_to_use = self.scraper
        else:
            session_to_use = self.session
        
        headers = {'User-Agent': self._get_random_user_agent()}
        
        try:
            start_time = time.time()
            
            # Делаем запрос с автоматическим следованием редиректам
            response = session_to_use.get(
                url, 
                headers=headers, 
                timeout=self.timeout,
                allow_redirects=True
            )
            response_time = round((time.time() - start_time) * 1000)
            
            # Извлекаем цепочку редиректов
            redirect_chain, final_url = self._extract_redirect_chain(response, response.history)
            redirect_count = len(redirect_chain)
            
            # Если есть редиректы, но финальный URL совпадает с исходным - что-то не так
            if redirect_count > 0 and final_url == url:
                final_url = redirect_chain[-1].get('location', url) if redirect_chain else url
            
            status_code = response.status_code
            
            # 1. Проверяем, не защита ли от ботов
            if status_code in [403, 503, 521] or self._is_bot_protection(response):
                # Пробуем обойти защиту если еще не использовали CloudScraper
                if self.use_stealth and not isinstance(session_to_use, type(self.scraper)) if hasattr(self, 'scraper') else False:
                    bypassed = self._try_bypass(final_url or url)
                    if bypassed and bypassed.get('success'):
                        bypass_response = bypassed['response']
                        bypass_chain, bypass_final = self._extract_redirect_chain(bypass_response, bypass_response.history)
                        return {
                            'title': title,
                            'url': url,
                            'final_url': bypass_final or final_url,
                            'redirect_chain': bypass_chain,
                            'redirect_count': len(bypass_chain),
                            'add_date': bookmark['add_date'],
                            'status_code': bypassed['status_code'],
                            'status_text': f'{bypassed["status_code"]} Работает (защита обойдена)',
                            'response_time': bypassed['response_time'],
                            'is_working': True,
                            'status_icon': '✅',
                            'category': 'working',
                            'original_block': status_code
                        }
                
                return {
                    'title': title,
                    'url': url,
                    'final_url': final_url or url,
                    'redirect_chain': redirect_chain,
                    'redirect_count': redirect_count,
                    'add_date': bookmark['add_date'],
                    'status_code': status_code,
                    'status_text': f'{status_code} Защита от ботов',
                    'response_time': response_time,
                    'is_working': False,
                    'status_icon': '🛡️',
                    'category': 'blocked'
                }
            
            # 2. Успешные ответы (200-399)
            if 200 <= status_code < 400:
                return {
                    'title': title,
                    'url': url,
                    'final_url': final_url or url,
                    'redirect_chain': redirect_chain,
                    'redirect_count': redirect_count,
                    'add_date': bookmark['add_date'],
                    'status_code': status_code,
                    'status_text': f'{status_code} {self._get_status_text(status_code)}',
                    'response_time': response_time,
                    'is_working': True,
                    'status_icon': '✅',
                    'category': 'working'
                }
            
            # 3. Ошибки сервера/клиента (404, 500, 502 и др.)
            return {
                'title': title,
                'url': url,
                'final_url': final_url or url,
                'redirect_chain': redirect_chain,
                'redirect_count': redirect_count,
                'add_date': bookmark['add_date'],
                'status_code': status_code,
                'status_text': f'{status_code} {self._get_status_text(status_code)}',
                'response_time': response_time,
                'is_working': False,
                'status_icon': '❌',
                'category': 'error'
            }
            
        except requests.exceptions.TooManyRedirects:
            # Слишком много редиректов
            return {
                'title': title,
                'url': url,
                'final_url': url,
                'redirect_chain': [],
                'redirect_count': self.max_redirects,
                'add_date': bookmark['add_date'],
                'status_code': 0,
                'status_text': f'Слишком много редиректов (>{self.max_redirects})',
                'response_time': 0,
                'is_working': False,
                'status_icon': '🔄',
                'category': 'error'
            }
        except requests.exceptions.ConnectionError:
            return {
                'title': title,
                'url': url,
                'final_url': url,
                'redirect_chain': [],
                'redirect_count': 0,
                'add_date': bookmark['add_date'],
                'status_code': 0,
                'status_text': 'Сайт недоступен (нет соединения)',
                'response_time': 0,
                'is_working': False,
                'status_icon': '💀',
                'category': 'dead'
            }
        except requests.exceptions.Timeout:
            return {
                'title': title,
                'url': url,
                'final_url': url,
                'redirect_chain': [],
                'redirect_count': 0,
                'add_date': bookmark['add_date'],
                'status_code': 408,
                'status_text': '408 Таймаут (сервер не отвечает)',
                'response_time': self.timeout * 1000,
                'is_working': False,
                'status_icon': '💀',
                'category': 'dead'
            }
        except Exception as e:
            return {
                'title': title,
                'url': url,
                'final_url': url,
                'redirect_chain': [],
                'redirect_count': 0,
                'add_date': bookmark['add_date'],
                'status_code': 0,
                'status_text': f'Ошибка: {str(e)[:40]}',
                'response_time': 0,
                'is_working': False,
                'status_icon': '⚠️',
                'category': 'error'
            }
    
    def _get_status_text(self, code):
        texts = {
            200: "OK", 201: "Created", 204: "No Content",
            301: "Moved Permanently", 302: "Found", 303: "See Other",
            304: "Not Modified", 307: "Temporary Redirect", 308: "Permanent Redirect",
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
            404: "Not Found", 408: "Request Timeout", 410: "Gone",
            429: "Too Many Requests", 500: "Internal Server Error",
            502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout",
            521: "Web Server Is Down"
        }
        return texts.get(code, "")
    
    def check_all_bookmarks(self, bookmarks):
        print(f"🚀 Начало проверки {len(bookmarks)} ссылок...")
        if self.use_stealth:
            print("🛡️ Режим обхода блокировок ВКЛЮЧЕН")
        print(f"🔄 Отслеживание редиректов (макс. {self.max_redirects})")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.check_url, bookmark): bookmark for bookmark in bookmarks}
            
            completed = 0
            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                completed += 1
                
                # Вывод прогресса с информацией о редиректах
                icon = result['status_icon']
                status = result['status_text'][:40]
                redirect_info = f" ↺{result['redirect_count']}" if result['redirect_count'] > 0 else ""
                print(f"[{completed}/{len(bookmarks)}] {icon} {result['title'][:35]} - {status}{redirect_info}")
        
        print("✅ Проверка завершена!")
        return self.results
    
    def generate_html_report(self, output_file='bookmarks_report.html'):
        """Генерация HTML отчета"""
        working = sum(1 for r in self.results if r['category'] == 'working')
        blocked = sum(1 for r in self.results if r['category'] == 'blocked')
        errors = sum(1 for r in self.results if r['category'] == 'error')
        dead = sum(1 for r in self.results if r['category'] == 'dead')
        
        # Статистика по редиректам
        redirects_total = sum(1 for r in self.results if r['redirect_count'] > 0)
        redirects_301 = sum(1 for r in self.results for rd in r.get('redirect_chain', []) if rd.get('status_code') == 301)
        redirects_302 = sum(1 for r in self.results for rd in r.get('redirect_chain', []) if rd.get('status_code') == 302)
        
        # Детализация по типам
        blocked_403 = sum(1 for r in self.results if r['category'] == 'blocked' and r['status_code'] == 403)
        blocked_503 = sum(1 for r in self.results if r['category'] == 'blocked' and r['status_code'] == 503)
        blocked_521 = sum(1 for r in self.results if r['category'] == 'blocked' and r['status_code'] == 521)
        
        errors_404 = sum(1 for r in self.results if r['category'] == 'error' and r['status_code'] == 404)
        errors_500 = sum(1 for r in self.results if r['category'] == 'error' and 500 <= r['status_code'] < 600)
        
        html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Отчет о проверке закладок</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 20px;
            padding: 30px;
            background: #f7f7f7;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}
        .stat-card:hover {{ transform: translateY(-2px); }}
        .stat-number {{ font-size: 32px; font-weight: bold; }}
        .stat-label {{ color: #666; margin-top: 5px; font-size: 14px; }}
        .stat-sub {{ font-size: 11px; color: #999; margin-top: 5px; }}
        
        .controls {{
            padding: 20px 30px;
            background: white;
            border-bottom: 1px solid #e0e0e0;
        }}
        .search-box {{
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            margin-bottom: 15px;
        }}
        .filter-buttons {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 15px;
        }}
        .filter-btn {{
            padding: 8px 20px;
            border: 2px solid #e0e0e0;
            background: white;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 14px;
            font-weight: 500;
        }}
        .filter-btn:hover {{
            background: #f0f0f0;
            transform: translateY(-1px);
        }}
        .filter-btn.active {{
            background: #667eea;
            color: white;
            border-color: #667eea;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th {{
            background: #f7f7f7;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #e0e0e0;
            cursor: pointer;
            user-select: none;
        }}
        th:hover {{ background: #efefef; }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #e0e0e0;
            vertical-align: top;
        }}
        tr:hover {{ background: #fafafa; }}
        
        .status-working {{ color: #10b981; font-weight: bold; }}
        .status-blocked {{ color: #f59e0b; font-weight: bold; }}
        .status-error {{ color: #ef4444; font-weight: bold; }}
        .status-dead {{ color: #6b7280; font-weight: bold; }}
        
        .url-link {{ color: #667eea; text-decoration: none; word-break: break-all; }}
        .url-link:hover {{ text-decoration: underline; }}
        .response-time {{ font-family: monospace; font-size: 12px; }}
        
        .redirect-info {{
            font-size: 11px;
            color: #888;
            margin-top: 4px;
            padding: 4px 6px;
            background: #f5f5f5;
            border-radius: 4px;
            font-family: monospace;
            word-break: break-all;
        }}
        .redirect-badge {{
            display: inline-block;
            background: #e0e7ff;
            color: #4338ca;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 10px;
            margin-left: 6px;
        }}
        
        .footer {{
            padding: 20px 30px;
            background: #f7f7f7;
            text-align: center;
            color: #666;
            font-size: 13px;
            line-height: 1.6;
        }}
        @media (max-width: 768px) {{
            .stats {{ grid-template-columns: 1fr; }}
            table {{ font-size: 12px; }}
            td, th {{ padding: 8px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Отчет о проверке закладок</h1>
            <p>Дата проверки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number" style="color: #667eea;">{len(self.results)}</div>
                <div class="stat-label">Всего закладок</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" style="color: #10b981;">{working}</div>
                <div class="stat-label">✅ Работающие</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" style="color: #f59e0b;">{blocked}</div>
                <div class="stat-label">🛡️ Заблокированные</div>
                <div class="stat-sub">403: {blocked_403} | 503: {blocked_503} | 521: {blocked_521}</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" style="color: #ef4444;">{errors}</div>
                <div class="stat-label">❌ Ошибки сайта</div>
                <div class="stat-sub">404: {errors_404} | 5xx: {errors_500}</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" style="color: #6b7280;">{dead}</div>
                <div class="stat-label">💀 Недоступные</div>
            </div>
        </div>
        
        <div class="stats" style="padding-top: 0;">
            <div class="stat-card">
                <div class="stat-number" style="color: #8b5cf6;">{redirects_total}</div>
                <div class="stat-label">↺ С редиректами</div>
                <div class="stat-sub">301: {redirects_301} | 302: {redirects_302}</div>
            </div>
        </div>
        
        <div class="controls">
            <input type="text" id="search" class="search-box" placeholder="🔍 Поиск по названию или URL..." onkeyup="applyFilters()">
            <div class="filter-buttons">
                <button class="filter-btn active" data-filter="all" onclick="setFilter('all')">📋 Все</button>
                <button class="filter-btn" data-filter="working" onclick="setFilter('working')">✅ Работающие</button>
                <button class="filter-btn" data-filter="blocked" onclick="setFilter('blocked')">🛡️ Заблокированные</button>
                <button class="filter-btn" data-filter="error" onclick="setFilter('error')">❌ Ошибки</button>
                <button class="filter-btn" data-filter="dead" onclick="setFilter('dead')">💀 Недоступные</button>
                <button class="filter-btn" data-filter="redirects" onclick="setFilter('redirects')">↺ С редиректами</button>
            </div>
        </div>
        
        <div style="overflow-x: auto;">
            <table id="bookmarks-table">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">Статус</th>
                        <th onclick="sortTable(1)">Название</th>
                        <th onclick="sortTable(2)">URL</th>
                        <th onclick="sortTable(3)">Код</th>
                        <th onclick="sortTable(4)">Время</th>
                        <th onclick="sortTable(5)">Дата</th>
                    </tr>
                </thead>
                <tbody>
"""
        
        for r in self.results:
            if r['category'] == 'working':
                status_class = "status-working"
                filter_category = 'working'
                status_display = f"{r['status_icon']} {r['status_text']}"
            elif r['category'] == 'blocked':
                status_class = "status-blocked"
                filter_category = 'blocked'
                status_display = f"{r['status_icon']} {r['status_code']} Защита от ботов"
            elif r['category'] == 'error':
                status_class = "status-error"
                filter_category = 'error'
                status_display = f"{r['status_icon']} {r['status_text']}"
            else:
                status_class = "status-dead"
                filter_category = 'dead'
                status_display = f"{r['status_icon']} {r['status_text']}"
            
            # Если есть редиректы, добавляем в категорию redirects для фильтрации
            has_redirects = r['redirect_count'] > 0
            if has_redirects and filter_category not in ['redirects']:
                filter_category = 'redirects'
            
            response_time_display = f"{r['response_time']} ms" if r['response_time'] > 0 else "N/A"
            
            # Формируем отображение URL с информацией о редиректах
            url_display = f'<a href="{r["url"]}" target="_blank" class="url-link">{self.escape_html(r["url"][:80])}</a>'
            if has_redirects and r['final_url'] and r['final_url'] != r['url']:
                final_url_short = r['final_url'][:60] + "..." if len(r['final_url']) > 60 else r['final_url']
                redirect_html = f'<div class="redirect-info">↺ {r["redirect_count"]} редирект(ов) → <a href="{r["final_url"]}" target="_blank" style="color:#667eea;">{self.escape_html(final_url_short)}</a></div>'
                url_display += redirect_html
                status_display += f' <span class="redirect-badge">↺{r["redirect_count"]}</span>'
            
            html_content += f"""
                    <tr class="bookmark-row" data-category="{filter_category}">
                        <td class="{status_class}">{status_display[:70]}</td>
                        <td>{self.escape_html(r['title'][:100])}</td>
                        <td>{url_display}</td>
                        <td>{r['status_code'] if r['status_code'] > 0 else 'N/A'}</td>
                        <td class="response-time">{response_time_display}</td>
                        <td>{r['add_date']}</td>
                    </tr>
"""
        
        html_content += """
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>
                <strong>📋 Легенда:</strong><br>
                ✅ <strong>Работающие</strong> - сайт доступен (коды 200-399)<br>
                🛡️ <strong>Заблокированные</strong> - сайт защищен от ботов (403, 503, 521)<br>
                ❌ <strong>Ошибки сайта</strong> - сайт работает, но вернул ошибку (404, 500, 502 и др.)<br>
                💀 <strong>Недоступные</strong> - сервер не отвечает (сайт вероятно умер)<br>
                ↺ <strong>С редиректами</strong> - URL перенаправляет на другой адрес
            </p>
        </div>
    </div>
    
    <script>
        let currentFilter = 'all';
        
        function applyFilters() {
            const searchTerm = document.getElementById('search').value.toLowerCase();
            const rows = document.getElementsByClassName('bookmark-row');
            
            for (let row of rows) {
                const category = row.getAttribute('data-category');
                const title = row.cells[1].innerText.toLowerCase();
                const url = row.cells[2].innerText.toLowerCase();
                
                let matchesFilter = false;
                if (currentFilter === 'all') {
                    matchesFilter = true;
                } else if (currentFilter === 'redirects') {
                    matchesFilter = (category === 'redirects');
                } else {
                    matchesFilter = (category === currentFilter);
                }
                
                const matchesSearch = title.includes(searchTerm) || url.includes(searchTerm);
                
                row.style.display = (matchesFilter && matchesSearch) ? '' : 'none';
            }
        }
        
        function setFilter(filter) {
            currentFilter = filter;
            const buttons = document.getElementsByClassName('filter-btn');
            for (let btn of buttons) {
                btn.classList.remove('active');
                if (btn.getAttribute('data-filter') === filter) {
                    btn.classList.add('active');
                }
            }
            applyFilters();
        }
        
        let sortDirection = {};
        
        function sortTable(columnIndex) {
            const table = document.getElementById('bookmarks-table');
            const tbody = table.getElementsByTagName('tbody')[0];
            const rows = Array.from(tbody.getElementsByClassName('bookmark-row'));
            
            if (!sortDirection[columnIndex]) {
                sortDirection[columnIndex] = 'asc';
            } else {
                sortDirection[columnIndex] = sortDirection[columnIndex] === 'asc' ? 'desc' : 'asc';
            }
            
            rows.sort((a, b) => {
                let aValue = a.cells[columnIndex].innerText;
                let bValue = b.cells[columnIndex].innerText;
                
                if (columnIndex === 3) {
                    aValue = parseInt(aValue) || 0;
                    bValue = parseInt(bValue) || 0;
                } else if (columnIndex === 4) {
                    aValue = parseInt(aValue) || 0;
                    bValue = parseInt(bValue) || 0;
                } else {
                    aValue = aValue.toLowerCase();
                    bValue = bValue.toLowerCase();
                }
                
                if (aValue < bValue) return sortDirection[columnIndex] === 'asc' ? -1 : 1;
                if (aValue > bValue) return sortDirection[columnIndex] === 'asc' ? 1 : -1;
                return 0;
            });
            
            for (let row of rows) {
                tbody.appendChild(row);
            }
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            applyFilters();
        });
    </script>
</body>
</html>
"""
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"📄 HTML отчет сохранен: {output_file}")
        return output_file
    
    def escape_html(self, text):
        return (text.replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('"', '&quot;')
                    .replace("'", '&#39;'))

def main():
    parser = argparse.ArgumentParser(description='Проверка закладок Firefox с отслеживанием редиректов')
    parser.add_argument('bookmarks_file', help='Путь к файлу закладок (bookmarks.html)')
    parser.add_argument('-o', '--output', default='bookmarks_report.html', help='Выходной HTML файл')
    parser.add_argument('-t', '--timeout', type=int, default=15, help='Таймаут в секундах (по умолчанию: 15)')
    parser.add_argument('-w', '--workers', type=int, default=3, help='Количество потоков (по умолчанию: 3)')
    parser.add_argument('-d', '--delay', type=float, default=0.5, help='Задержка между запросами')
    parser.add_argument('-r', '--max-redirects', type=int, default=10, help='Максимум редиректов (по умолчанию: 10)')
    parser.add_argument('--no-stealth', action='store_true', help='Отключить обход блокировок')
    
    args = parser.parse_args()
    
    try:
        checker = BookmarkChecker(
            timeout=args.timeout,
            max_workers=args.workers,
            delay=args.delay,
            use_stealth=not args.no_stealth,
            max_redirects=args.max_redirects
        )
        
        bookmarks = checker.parse_bookmarks_html(args.bookmarks_file)
        
        if not bookmarks:
            print("⚠️ Закладки не найдены или файл пуст")
            return
        
        checker.check_all_bookmarks(bookmarks)
        report_file = checker.generate_html_report(args.output)
        
        # Итоговая статистика
        working = sum(1 for r in checker.results if r['category'] == 'working')
        blocked = sum(1 for r in checker.results if r['category'] == 'blocked')
        errors = sum(1 for r in checker.results if r['category'] == 'error')
        dead = sum(1 for r in checker.results if r['category'] == 'dead')
        redirects = sum(1 for r in checker.results if r['redirect_count'] > 0)
        
        print("\n" + "="*50)
        print("📊 СТАТИСТИКА ПРОВЕРКИ:")
        print(f"   ✅ Работающие: {working} ({working/len(checker.results)*100:.1f}%)")
        print(f"   🛡️ Заблокированные (403/503/521): {blocked}")
        print(f"   ❌ Ошибки сайта (404, 500 и др.): {errors}")
        print(f"   💀 Недоступные (сервер не отвечает): {dead}")
        print(f"   ↺ С редиректами: {redirects}")
        print(f"   📄 Отчет сохранен: {report_file}")
        print("="*50)
        
    except FileNotFoundError:
        print(f"❌ Ошибка: Файл '{args.bookmarks_file}' не найден")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()