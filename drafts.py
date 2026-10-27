"""Черновики: предложения заказчикам, переводы, статьи, документация. Ничего не отправляется автоматически —
владелец проверяет и отправляет сам. Без подключённого ИИ используются шаблоны с полями для заполнения."""
import time
from . import llm
from .db import get, log, err

SYSTEM = ("Ты помощник фрилансера. Пиши только на основе данных из задания и профиля. НЕ выдумывай опыт, образование, награды, "
          "ссылки, сроки и цены: если данных нет — оставляй поле в квадратных скобках [ТАК]. Пиши коротко и по делу.")
KINDS = ("proposal", "translation", "article", "docs")
AGENT = {"proposal": "B16", "translation": "B02", "article": "B01", "docs": "A10"}

def _prompt(kind, opp, profile, lang):
    brief = f'Заголовок: {opp["title"]}\nОписание: {(opp["description"] or "")[:1500]}\nСсылка: {opp["url"]}'
    prof = f"\nПрофиль исполнителя: {profile}" if profile else "\nПрофиль исполнителя не задан — используй поля [ТАК]."
    if kind == "proposal":
        return f"Составь короткое предложение заказчику (до 150 слов, на языке объявления).{prof}\n\n{brief}"
    if kind == "translation":
        return f"Переведи на {lang} текст ниже, сохрани смысл и форматирование. Если текста для перевода нет — переведи заголовок и описание.\n\n{brief}"
    if kind == "article":
        return f"Подготовь черновик статьи (план + вступление + 3 раздела, ~400 слов) по теме задания. Язык: {lang}.{prof}\n\n{brief}"
    return f"Подготовь черновик документации: структура разделов + текст вводного раздела и примера использования. Язык: {lang}.\n\n{brief}"

def template(kind, opp, profile, lang):
    who = profile or "[1–2 предложения: ваш релевантный опыт]"
    if kind == "proposal":
        return (f'Hello,\n\nI saw "{opp["title"]}" and would like to help.\n{who}\n\n'
                f"What I will deliver: [перечислите результат по пунктам из объявления]\nTimeline: [срок]   Rate: [ставка]\n"
                f"Relevant sample: [ссылка на пример]\n\nBest regards,\n[Имя]")
    if kind == "translation":
        return f"[Шаблон: ИИ не подключён] Вставьте исходный текст для перевода на {lang}.\n\nЗадание: {opp['title']}\n{(opp['description'] or '')[:600]}"
    if kind == "article":
        return f"[Шаблон: ИИ не подключён]\nТема: {opp['title']}\n1. Вступление\n2. Раздел 1 [..]\n3. Раздел 2 [..]\n4. Раздел 3 [..]\n5. Вывод"
    return f"[Шаблон: ИИ не подключён]\nДокументация: {opp['title']}\n1. Назначение\n2. Установка\n3. Быстрый старт\n4. Примеры\n5. FAQ"

def make(c, task_id, kind="proposal", lang="English"):
    if kind not in KINDS:
        raise ValueError(f"тип черновика: {', '.join(KINDS)}")
    opp = c.execute("SELECT o.* FROM tasks t JOIN opportunities o ON o.id=t.opp_id WHERE t.id=?", (task_id,)).fetchone()
    if not opp:
        raise ValueError("задача не найдена")
    profile = get(c, "profile", "")
    content, origin = None, "template"
    try:
        content = llm.complete(SYSTEM, _prompt(kind, opp, profile, lang))
        if content:
            origin = "llm"
    except llm.LLMError as e:
        err(c, "llm", e)
    content = content or template(kind, opp, profile, lang)
    cur = c.execute("INSERT INTO drafts(task_id,kind,content,origin,ts) VALUES(?,?,?,?,?)", (task_id, kind, content, origin, time.time()))
    c.commit()
    log(c, AGENT[kind], "draft_created", f"task={task_id} kind={kind} origin={origin}")
    return cur.lastrowid, origin, content
