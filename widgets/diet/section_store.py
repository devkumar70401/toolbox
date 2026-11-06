import os
import re
import json
import fcntl
from datetime import datetime
from pathlib import Path

DEFAULT_DAILY_DIR = Path(os.path.expanduser("~/SE/toolbox/daily")).resolve()


class TaskItem:
    def __init__(self, text: str, completed: bool = False, raw_line: str = ""):
        self.text = text
        self.completed = completed
        self.raw_line = raw_line

    def to_markdown(self) -> str:
        marker = "x" if self.completed else " "
        return f"- [{marker}] {self.text}"


class MultiSectionMarkdownStore:
    def __init__(self, section_type: str = "work", config_dir: Path = None, daily_dir: Path = DEFAULT_DAILY_DIR):
        """
        section_type: "work", "diet", or "routines"
        """
        self.section_type = section_type.lower()
        self.daily_dir = Path(daily_dir)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        
        if config_dir is None:
            self.config_dir = Path.home() / ".config" / "daily-todo-widget"
        else:
            self.config_dir = Path(config_dir)
            
        self.config_file = self.config_dir / "config.json"
        self.config = self.load_config()
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.last_mtime = 0.0

    def set_section(self, section_type: str):
        self.section_type = section_type.lower()

    def load_config(self) -> dict:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        default_cfg = {
            "x": 4110,
            "y": 505,
            "width": 360,
            "height": 520,
            "carry_over_incomplete": True,
            "opacity": 0.82,
            "always_on_top": False
        }
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    default_cfg.update(cfg)
            except Exception:
                pass
        return default_cfg

    def save_config(self, cfg: dict):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            self.config = cfg
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_file_path(self, date_str: str = None) -> Path:
        if not date_str:
            date_str = self.current_date
        return self.daily_dir / f"{date_str}.md"

    def ensure_today_file(self) -> Path:
        today_file = self.get_file_path(self.current_date)
        if not today_file.exists():
            self._initialize_today_file(today_file)
        else:
            self._ensure_sections_exist(today_file)
        return today_file

    def _get_default_diet_items(self, date_obj: datetime = None) -> list:
        if date_obj is None:
            try:
                date_obj = datetime.strptime(self.current_date, "%Y-%m-%d")
            except Exception:
                date_obj = datetime.now()

        template_file = self.daily_dir / "templates" / "diet_template.json"
        daily_items = []
        sunday_items = []

        if template_file.exists():
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    daily_items = data.get("daily_items", [])
                    sunday_items = data.get("sunday_items", [])
            except Exception as e:
                print(f"Error loading diet template: {e}")

        if not daily_items:
            daily_items = [
                "Pumpkin seeds",
                "Chia seeds",
                "Roasted chana",
                "Almonds & Walnuts",
                "Monohydrate creatine",
                "Moringa powder in dish",
                "Curd",
                "One glass of milk"
            ]
            sunday_items = [
                "D3 capsule on sunday"
            ]

        items = []
        for item in daily_items:
            if item not in items:
                items.append(item)

        if date_obj.weekday() == 6:  # Sunday
            for item in sunday_items:
                if item not in items:
                    items.append(item)

        return items

    def _get_default_routine_items(self) -> list:
        template_file = self.daily_dir / "templates" / "routines_template.json"
        if template_file.exists():
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("daily_items", [])
            except Exception as e:
                print(f"Error loading routines template: {e}")

        return [
            "Check emails",
            "Bath & freshen up",
            "Check Instagram",
            "Brush teeth (night)",
        ]

    def _find_incomplete_work_from_previous_day(self) -> list:
        md_files = sorted(
            [f for f in self.daily_dir.glob("*.md") if f.stem < self.current_date and re.match(r"^\d{4}-\d{2}-\d{2}$", f.stem)],
            key=lambda x: x.stem
        )
        if not md_files:
            return []

        last_file = md_files[-1]
        incomplete = []
        try:
            with open(last_file, "r", encoding="utf-8") as f:
                in_work_section = False
                task_regex = re.compile(r"^\s*-\s*\[([ ])\]\s*(.+)$")
                header_regex = re.compile(r"^##\s+(.+)$")

                for line in f:
                    hm = header_regex.match(line)
                    if hm:
                        header_text = hm.group(1).lower()
                        in_work_section = ("work" in header_text or "today" in header_text) and not ("diet" in header_text or "food" in header_text or "nutrition" in header_text or "pomodoro" in header_text or "routine" in header_text)
                        continue
                    
                    if in_work_section:
                        m = task_regex.match(line)
                        if m:
                            incomplete.append(m.group(2).strip())
        except Exception as e:
            print(f"Error reading previous day work tasks: {e}")
        return incomplete

    def _initialize_today_file(self, target_path: Path):
        try:
            with open(target_path, "a+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0, os.SEEK_END)
                    if f.tell() > 0:
                        self.last_mtime = target_path.stat().st_mtime
                        return

                    date_obj = datetime.strptime(self.current_date, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%A, %d %B %Y")
                    
                    carry_over = self.config.get("carry_over_incomplete", True)
                    carried_work = []
                    if carry_over:
                        carried_work = self._find_incomplete_work_from_previous_day()

                    lines = [
                        f"# Daily Tasks — {formatted_date}\n\n",
                        "## 💼 Work\n"
                    ]
                    if carried_work:
                        for t in carried_work:
                            lines.append(f"- [ ] {t}\n")

                    lines.append("\n## 🥗 Diet & Nutrition\n")
                    diet_items = self._get_default_diet_items(date_obj)
                    for d in diet_items:
                        lines.append(f"- [ ] {d}\n")

                    lines.append("\n## 🔄 Daily Routines\n")
                    routine_items = self._get_default_routine_items()
                    for r in routine_items:
                        lines.append(f"- [ ] {r}\n")

                    f.seek(0)
                    f.writelines(lines)
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            self.last_mtime = target_path.stat().st_mtime
        except Exception as e:
            print(f"Error initializing today file: {e}")

    def _ensure_sections_exist(self, target_path: Path):
        """Ensure ## 💼 Work, ## 🥗 Diet & Nutrition, and ## 🔄 Daily Routines exist."""
        try:
            with open(target_path, "r+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    content = f.read()
                    has_work = bool(re.search(r"^##\s+.*(?:Work|Today's Tasks)", content, re.MULTILINE | re.IGNORECASE))
                    has_diet = bool(re.search(r"^##\s+.*(?:Diet|Food|Nutrition)", content, re.MULTILINE | re.IGNORECASE))
                    has_routines = bool(re.search(r"^##\s+.*(?:Routine)", content, re.MULTILINE | re.IGNORECASE))

                    modified = False

                    if not has_work:
                        work_lines = "## 💼 Work\n"
                        carry_over = self.config.get("carry_over_incomplete", True)
                        carried = self._find_incomplete_work_from_previous_day() if carry_over else []
                        for t in carried:
                            work_lines += f"- [ ] {t}\n"
                        work_lines += "\n"

                        title_match = re.search(r"^(#\s+[^\n]+\n+)", content)
                        if title_match:
                            idx = title_match.end()
                            content = content[:idx] + work_lines + content[idx:]
                        else:
                            content = work_lines + content
                        modified = True

                    if not has_diet:
                        diet_content = "\n## 🥗 Diet & Nutrition\n"
                        diet_items = self._get_default_diet_items()
                        for d in diet_items:
                            diet_content += f"- [ ] {d}\n"
                        
                        routines_match = re.search(r"^(##\s+.*(?:Routine))", content, re.MULTILINE | re.IGNORECASE)
                        pomo_match = re.search(r"^(##\s+.*Pomodoro)", content, re.MULTILINE | re.IGNORECASE)
                        if routines_match:
                            idx = routines_match.start()
                            content = content[:idx] + diet_content + "\n" + content[idx:]
                        elif pomo_match:
                            idx = pomo_match.start()
                            content = content[:idx] + diet_content + "\n" + content[idx:]
                        else:
                            if not content.endswith("\n"):
                                content += "\n"
                            content += diet_content
                        modified = True

                    if not has_routines:
                        routines_content = "\n## 🔄 Daily Routines\n"
                        routine_items = self._get_default_routine_items()
                        for r in routine_items:
                            routines_content += f"- [ ] {r}\n"

                        pomo_match = re.search(r"^(##\s+.*Pomodoro)", content, re.MULTILINE | re.IGNORECASE)
                        if pomo_match:
                            idx = pomo_match.start()
                            content = content[:idx] + routines_content + "\n" + content[idx:]
                        else:
                            if not content.endswith("\n"):
                                content += "\n"
                            content += routines_content
                        modified = True

                    if modified:
                        f.seek(0)
                        f.write(content)
                        f.truncate()
                        self.last_mtime = target_path.stat().st_mtime
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:
            print(f"Error ensuring sections: {e}")

    def _is_matching_header(self, header_text: str, section: str = None) -> bool:
        sec = (section or self.section_type).lower()
        header_lower = header_text.lower()
        if "pomodoro" in header_lower:
            return False
        if sec == "work":
            return ("work" in header_lower or "today" in header_lower) and not ("diet" in header_lower or "food" in header_lower or "nutrition" in header_lower or "routine" in header_lower)
        elif sec == "diet":
            return ("diet" in header_lower or "food" in header_lower or "nutrition" in header_lower) and not ("work" in header_lower or "routine" in header_lower)
        elif sec in ("routines", "routine"):
            return "routine" in header_lower and not ("work" in header_lower or "diet" in header_lower or "food" in header_lower or "nutrition" in header_lower)
        return False

    def load_tasks(self, section: str = None) -> list[TaskItem]:
        sec = section or self.section_type
        target_path = self.ensure_today_file()
        try:
            self.last_mtime = target_path.stat().st_mtime
        except Exception:
            self.last_mtime = 0.0

        tasks = []
        task_regex = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.+)$")
        header_regex = re.compile(r"^##\s+(.+)$")
        in_my_section = False

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                for line in f:
                    hm = header_regex.match(line)
                    if hm:
                        in_my_section = self._is_matching_header(hm.group(1), section=sec)
                        continue

                    if in_my_section:
                        m = task_regex.match(line)
                        if m:
                            is_done = (m.group(1).lower() == "x")
                            text = m.group(2).strip()
                            tasks.append(TaskItem(text=text, completed=is_done, raw_line=line))
        except Exception as e:
            print(f"Error reading tasks for {sec}: {e}")

        return tasks

    def toggle_task(self, index: int, completed: bool, section: str = None):
        sec = section or self.section_type
        target_path = self.ensure_today_file()
        header_regex = re.compile(r"^##\s+(.+)$")
        task_regex = re.compile(r"^(\s*-\s*\[)([ xX])(\]\s*.+)$")
        new_lines = []
        in_my_section = False
        current_section_idx = 0

        try:
            with open(target_path, "r+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    for line in f:
                        hm = header_regex.match(line)
                        if hm:
                            in_my_section = self._is_matching_header(hm.group(1), section=sec)
                            new_lines.append(line)
                            continue

                        if in_my_section:
                            m = task_regex.match(line)
                            if m:
                                if current_section_idx == index:
                                    marker = "x" if completed else " "
                                    rest = m.group(3).rstrip("\r\n")
                                    line = f"{m.group(1)}{marker}{rest}\n"
                                current_section_idx += 1

                        new_lines.append(line)

                    f.seek(0)
                    f.writelines(new_lines)
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

            self.last_mtime = target_path.stat().st_mtime
        except Exception as e:
            print(f"Error toggling task in {sec}: {e}")

    def add_task(self, text: str, section: str = None):
        sec = section or self.section_type
        text = " ".join(text.splitlines()).strip()
        while text.startswith("#"):
            text = text.lstrip("#").strip()
        while True:
            new_text = re.sub(r"^[-*+]\s*(\[[ xX]?\]\s*)?", "", text).strip()
            if new_text == text:
                break
            text = new_text
        if not text:
            return

        target_path = self.ensure_today_file()
        header_regex = re.compile(r"^##\s+(.+)$")
        new_lines = []
        in_my_section = False
        inserted = False

        try:
            with open(target_path, "r+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    lines = f.readlines()
                    i = 0
                    while i < len(lines):
                        line = lines[i]
                        hm = header_regex.match(line)
                        if hm:
                            if in_my_section and not inserted:
                                new_lines.append(f"- [ ] {text}\n")
                                inserted = True
                            in_my_section = self._is_matching_header(hm.group(1), section=sec)

                        new_lines.append(line)
                        i += 1

                    if in_my_section and not inserted:
                        if not new_lines[-1].endswith("\n"):
                            new_lines[-1] += "\n"
                        new_lines.append(f"- [ ] {text}\n")
                        inserted = True

                    if not inserted:
                        if sec == "work":
                            header = "## 💼 Work\n"
                        elif sec == "diet":
                            header = "## 🥗 Diet & Nutrition\n"
                        else:
                            header = "## 🔄 Daily Routines\n"
                        new_lines.append(f"\n{header}- [ ] {text}\n")

                    f.seek(0)
                    f.writelines(new_lines)
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

            self.last_mtime = target_path.stat().st_mtime
        except Exception as e:
            print(f"Error adding task in {sec}: {e}")

    def delete_task(self, index: int, section: str = None):
        sec = section or self.section_type
        target_path = self.ensure_today_file()
        header_regex = re.compile(r"^##\s+(.+)$")
        task_regex = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.+)$")
        new_lines = []
        in_my_section = False
        current_section_idx = 0

        try:
            with open(target_path, "r+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    for line in f:
                        hm = header_regex.match(line)
                        if hm:
                            in_my_section = self._is_matching_header(hm.group(1), section=sec)
                            new_lines.append(line)
                            continue

                        if in_my_section:
                            m = task_regex.match(line)
                            if m:
                                if current_section_idx == index:
                                    current_section_idx += 1
                                    continue
                                current_section_idx += 1

                        new_lines.append(line)

                    f.seek(0)
                    f.writelines(new_lines)
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

            self.last_mtime = target_path.stat().st_mtime
        except Exception as e:
            print(f"Error deleting task in {sec}: {e}")

    def check_date_rollover(self) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.current_date:
            self.current_date = today
            return True
        return False

    def check_file_changed(self) -> bool:
        target_path = self.get_file_path()
        if not target_path.exists():
            return True
        try:
            mtime = target_path.stat().st_mtime
            if abs(mtime - self.last_mtime) > 1e-4:
                return True
        except Exception:
            pass
        return False
