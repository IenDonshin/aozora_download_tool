import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import requests
from bs4 import BeautifulSoup
import os
import re
import time
from urllib.parse import urljoin
import zipfile
import threading

class AozoraScraper:
    """
    青空文庫のウェブサイトから情報を取得し、ファイルをダウンロードするバックエンドロジック。
    """
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://www.aozora.gr.jp/"

    def _get_soup(self, url):
        """指定されたURLからHTMLを取得し、BeautifulSoupオブジェクトを返す。"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            return BeautifulSoup(response.text, 'html.parser')
        except requests.exceptions.RequestException as e:
            print(f"URLへのアクセスエラー: {url}, {e}")
            return None

    def get_author_works_info(self, author_id: str):
        """作家IDを基に、作家名と作品情報を取得する。"""
        author_page_url = urljoin(self.base_url, f"index_pages/person{author_id}.html")
        soup = self._get_soup(author_page_url)
        if not soup:
            return None, None
        
        author_name = "不明"
        try:
            author_name_header = soup.find('td', class_='header', string='作家名：')
            if author_name_header:
                author_name_cell = author_name_header.find_next_sibling('td')
                if author_name_cell:
                    author_name = author_name_cell.get_text(strip=True)
        except Exception as e:
            print(f"作家名の取得中にエラーが発生しました: {e}")
            author_name = "取得失敗"

        works_list = []
        work_elements = soup.select('ol > li, ul > li')

        for elem in work_elements:
            link = elem.find('a')
            if not link or "person" in link.get('href', ''):
                continue
            
            relative_path = link.get('href')
            work_card_url = urljoin(author_page_url, relative_path)
            
            match = re.search(r'cards/(\d+)/card(\d+)\.html', work_card_url)
            if not match: continue

            work_id = match.group(2)
            
            main_title = link.get_text(strip=True)
            full_list_item_text = elem.get_text(" ", strip=True)
            subtitle_match = re.search(re.escape(main_title) + r'\s*(.*?)\s*（', full_list_item_text)
            if subtitle_match and subtitle_match.group(1):
                subtitle = subtitle_match.group(1).strip()
                work_title = f"{main_title} {subtitle}"
            else:
                work_title = main_title

            list_item_text = elem.get_text()
            notation_match = re.search(r'（([^）]+)', list_item_text)
            notation = notation_match.group(1).split('、')[0] if notation_match else ""

            time.sleep(0.05)
            work_soup = self._get_soup(work_card_url)
            if not work_soup: continue
            
            publication_year = "不明"
            try:
                initial_publication = ""
                header = work_soup.find('td', class_='header', string='初出：')
                if header:
                    sibling_cell = header.find_next_sibling('td')
                    if sibling_cell:
                        initial_publication = sibling_cell.get_text(strip=True)
                
                if not initial_publication:
                    h2_base_text = work_soup.find('h2', string='底本データ')
                    if h2_base_text:
                        base_text_table = h2_base_text.find_next_sibling('table')
                        if base_text_table:
                            base_text_header = base_text_table.find('td', class_='header', string='初版発行日：')
                            if base_text_header:
                                date_cell = base_text_header.find_next_sibling('td')
                                if date_cell:
                                    initial_publication = date_cell.get_text(strip=True)
                
                if initial_publication:
                    year_match = re.search(r"(\d{4})", re.sub(r"（[^）]*）", "", initial_publication))
                    if year_match:
                        publication_year = year_match.group(1)
            except Exception as e:
                print(f"{work_card_url} の年取得中にエラーが発生しました: {e}")

            formats = set()
            for dl_link in work_soup.select('table.download a[href]'):
                href = dl_link.get('href', '')
                file_ext = os.path.splitext(href)[1].replace('.', '').lower()
                if file_ext:
                    if file_ext == 'html' and 'files' not in href:
                        continue
                    formats.add(file_ext)
            
            works_list.append({
                'id': work_id,
                'title': work_title,
                'notation': notation,
                'year': publication_year,
                'formats': sorted(list(formats)),
                'url': work_card_url,
                'checked': False
            })
        return author_name, works_list

    def download_and_process_work(self, work_info, file_format, save_dir):
        """単一の作品をダウンロードして処理し、優先順位フォールバック機能付き。"""
        work_soup = self._get_soup(work_info['url'])
        if not work_soup:
            return f"作品ページにアクセスできません: {work_info['title']}"

        download_links = {}
        for link in work_soup.select('table.download a[href]'):
            href = link.get('href')
            ext = os.path.splitext(href)[1].replace('.', '').lower()
            if ext in work_info['formats']:
                full_url = urljoin(work_info['url'], href)
                if ext not in download_links:
                    download_links[ext] = full_url

        download_url = None
        actual_format_used = None
        priority_order = [file_format, 'zip', 'html']
        
        available_formats = sorted(download_links.keys(), key=lambda x: (priority_order.index(x) if x in priority_order else 99))

        if available_formats:
            actual_format_used = available_formats[0]
            download_url = download_links[actual_format_used]
            if actual_format_used != file_format:
                 print(f"情報: 形式 '{file_format}' が見つかりません。'{work_info['title']}' を '{actual_format_used}' 形式でダウンロードします。")

        if not download_url:
            return f"ダウンロード可能な形式が見つかりません: {work_info['title']}"

        try:
            response = self.session.get(download_url, timeout=30)
            response.raise_for_status()
            safe_title = re.sub(r'[\\|/|:|*|?|"|<|>|\|]', '_', work_info['title'])
            
            if actual_format_used == 'zip':
                zip_filename = f"{safe_title}_{work_info['id']}.zip"
                zip_path = os.path.join(save_dir, zip_filename)
                with open(zip_path, 'wb') as f: f.write(response.content)
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        try: decoded_member = member.encode('cp437').decode('shift_jis')
                        except: decoded_member = member
                        
                        # ファイル名変更ロジック
                        _root, extension = os.path.splitext(decoded_member)
                        new_filename = f"{safe_title}{extension}"
                        
                        new_path = os.path.join(save_dir, new_filename)
                        
                        # ファイルを新しい名前で直接書き出す
                        file_content = zip_ref.read(member)
                        if os.path.exists(new_path): os.remove(new_path)
                        with open(new_path, 'wb') as f: f.write(file_content)
                        
                os.remove(zip_path)
                return f"解凍完了: {work_info['title']}"
            else:
                save_path = os.path.join(save_dir, f"{safe_title}.{actual_format_used}")
                with open(save_path, 'wb') as f: f.write(response.content)
                return f"保存完了: {work_info['title']}"

        except (requests.exceptions.RequestException, zipfile.BadZipFile, OSError) as e:
            return f"ダウンロード/処理エラー: {work_info['title']}, {e}"

class App(tk.Tk):
    UNCHECKED, CHECKED = "☐", "☑"
    def __init__(self):
        super().__init__()
        self.title("青空文庫 ダウンロードツール")
        self.geometry("850x600")
        self.minsize(700, 400)

        self.scraper = AozoraScraper()
        self.works_data = []

        main_frame = ttk.Frame(self, padding="10"); main_frame.pack(fill="both", expand=True)
        top_frame = ttk.Frame(main_frame); top_frame.pack(fill="x", pady=5)

        ttk.Label(top_frame, text="作家ID:").pack(side="left", padx=(0, 5))
        self.author_id_entry = ttk.Entry(top_frame, width=10); self.author_id_entry.pack(side="left", padx=5)

        self.query_button = ttk.Button(top_frame, text="作品を照会", command=self.start_query_works)
        self.query_button.pack(side="left", padx=5)
        
        self.author_name_var = tk.StringVar(value="作家名: 未照会")
        ttk.Label(top_frame, textvariable=self.author_name_var, foreground="blue").pack(side="left", padx=10)

        self.selection_count_var = tk.StringVar(value="選択数: 0")
        ttk.Label(top_frame, textvariable=self.selection_count_var).pack(side="right", padx=5)

        tree_frame = ttk.Frame(main_frame); tree_frame.pack(fill="both", expand=True, pady=5)
        columns = ("check", "id", "title", "notation", "year", "formats")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        self.tree.heading("check", text="選択"); self.tree.column("check", width=50, anchor="center", stretch=False)
        self.tree.heading("id", text="作品ID"); self.tree.column("id", width=60, anchor="center", stretch=False)
        self.tree.heading("title", text="タイトル"); self.tree.column("title", width=350)
        self.tree.heading("notation", text="表記"); self.tree.column("notation", width=120)
        self.tree.heading("year", text="初出年"); self.tree.column("year", width=80, anchor="center", stretch=False)
        self.tree.heading("formats", text="形式"); self.tree.column("formats", width=100, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y"); hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind('<Button-1>', self.on_tree_click)

        path_frame = ttk.Frame(main_frame); path_frame.pack(fill="x", pady=(5, 2))
        ttk.Label(path_frame, text="保存先:").pack(side="left", padx=(0, 5))
        self.save_dir_entry = ttk.Entry(path_frame)
        self.save_dir_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.save_dir_entry.insert(0, os.path.join(os.path.expanduser("~"), "Downloads", "aozora_books"))
        self.browse_button = ttk.Button(path_frame, text="参照...", command=self.browse_save_directory)
        self.browse_button.pack(side="left", padx=5)

        action_frame = ttk.Frame(main_frame); action_frame.pack(fill="x", pady=(2, 5))
        ttk.Label(action_frame, text="形式:").pack(side="left", padx=(0, 5))
        self.format_combo = ttk.Combobox(action_frame, width=15, state="readonly")
        self.format_combo.pack(side="left", padx=5)
        
        self.download_all_button = ttk.Button(action_frame, text="すべてダウンロード", command=lambda: self.start_download(False))
        self.download_all_button.pack(side="right", padx=(5,0))
        self.download_selected_button = ttk.Button(action_frame, text="選択をダウンロード", command=lambda: self.start_download(True))
        self.download_selected_button.pack(side="right", padx=5)

        self.status_var = tk.StringVar(); self.status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w", padding=5)
        self.status_bar.pack(side="bottom", fill="x"); self.status_var.set("準備完了")

    def on_tree_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell": return
        if self.tree.identify_column(event.x) == "#1":
            item_id = self.tree.identify_row(event.y)
            if not item_id: return
            index = self.tree.index(item_id)
            work = self.works_data[index]
            work['checked'] = not work['checked']
            check_char = self.CHECKED if work['checked'] else self.UNCHECKED
            self.tree.item(item_id, values=(check_char, work['id'], work['title'], work['notation'], work['year'], ", ".join(work['formats'])))
            self.update_selection_count()

    def update_selection_count(self):
        count = sum(1 for work in self.works_data if work['checked'])
        self.selection_count_var.set(f"選択数: {count}")

    def browse_save_directory(self):
        directory = filedialog.askdirectory(title="保存先フォルダを選択")
        if directory: self.save_dir_entry.delete(0, tk.END); self.save_dir_entry.insert(0, directory)

    def set_ui_state(self, state):
        for widget in [self.query_button, self.download_selected_button, self.download_all_button, self.browse_button, self.author_id_entry, self.format_combo]:
            widget.config(state=state)

    def start_query_works(self):
        author_id = self.author_id_entry.get().strip()
        if not author_id.isdigit(): messagebox.showerror("エラー", "有効な作家ID（数字）を入力してください。"); return
        self.set_ui_state("disabled"); self.status_var.set(f"作家ID: {author_id} の作品を照会中...")
        for i in self.tree.get_children(): self.tree.delete(i)
        self.works_data.clear()
        self.author_name_var.set("作家名: 照会中..."); self.format_combo.set(''); self.format_combo['values'] = []
        threading.Thread(target=self.query_works_thread, args=(author_id,), daemon=True).start()

    def query_works_thread(self, author_id):
        author_name, new_data = self.scraper.get_author_works_info(author_id)
        self.after(0, self.update_treeview, author_name, new_data)

    def update_treeview(self, author_name, new_data):
        self.works_data = new_data if new_data is not None else []
        self.update_selection_count()
        self.author_name_var.set(f"作家名: {author_name or '取得失敗'}")

        if new_data is None: messagebox.showerror("エラー", "作品情報の取得に失敗しました。"); self.status_var.set("照会エラー")
        elif not new_data: messagebox.showinfo("情報", "この作家の作品は見つかりませんでした。"); self.status_var.set("作品が見つかりません")
        else:
            for work in self.works_data: self.tree.insert("", "end", values=(self.UNCHECKED, work['id'], work['title'], work['notation'], work['year'], ", ".join(work['formats'])))
            all_formats = sorted(list(set(f for w in self.works_data for f in w['formats'])))
            
            priority_order = ['zip', 'html']
            sorted_formats = sorted(all_formats, key=lambda x: (priority_order.index(x) if x in priority_order else 99))
            self.format_combo['values'] = sorted_formats
            if sorted_formats:
                self.format_combo.set(sorted_formats[0])
            
            self.status_var.set(f"{len(self.works_data)}件の作品が見つかりました。")
        self.set_ui_state("normal")

    def start_download(self, selected=False):
        save_dir = self.save_dir_entry.get().strip();
        if not save_dir: messagebox.showerror("エラー", "保存先フォルダを指定してください。"); return
        os.makedirs(save_dir, exist_ok=True)
        
        if selected: work_items_to_download = [w for w in self.works_data if w['checked']]
        else: work_items_to_download = self.works_data
        
        if not work_items_to_download: messagebox.showwarning("警告", "ダウンロードする作品がありません。"); return
        
        file_format = self.format_combo.get()
        if not file_format: messagebox.showerror("エラー", "ダウンロード形式を選択してください。"); return
        
        self.set_ui_state("disabled")
        threading.Thread(target=self.download_thread, args=(work_items_to_download, file_format, save_dir), daemon=True).start()

    def download_thread(self, works, file_format, save_dir):
        total = len(works)
        success_count = 0
        for i, work in enumerate(works):
            self.after(0, lambda msg=f"[{i+1}/{total}] ダウンロード中: {work['title']}": self.status_var.set(msg))
            result = self.scraper.download_and_process_work(work, file_format, save_dir)
            if "エラー" not in result:
                success_count += 1
            print(result)
            time.sleep(0.1)
        self.after(0, self.finish_download, success_count, total, save_dir)

    def finish_download(self, success_count, total_attempted, save_dir):
        self.status_var.set(f"処理完了: {success_count}/{total_attempted} 件のダウンロードに成功しました。")
        messagebox.showinfo("完了", f"保存先フォルダ:\n{save_dir}\n\n{success_count}/{total_attempted} 件のダウンロード処理が完了しました。")
        self.set_ui_state("normal")

if __name__ == '__main__':
    app = App()
    app.mainloop()
