# Отчёт по проектной практике
**Тема:** «Автоматизация внутренних бизнес-процессов университета. 2ГИС»
**Студент:** Озеров Богдан Евгеньевич 
**Период:** 03.02.2025 - 24.05.2025  
**Руководитель:** Меньшикова Наталия Павловна 

##  Цели и задачи
1. Разработка Telegram-бота для установки напоминаний и повторяющихся уведомлений
2. Создание презентационного сайта проектной деятельности

##  Технологический стек
**Backend:**
- Python 3.10
- Библиотеки: asyncio, sqlite3, datetime, telegram, ApScheduler

**Frontend:**
- HTML5, CSS3, JS


##  Ход работы
### Этап 1: Анализ (03.2025)
- Проведено исследование HTML и CSS структур

### Этап 2: Разработка (03-04.2025)
**Telegram-бот:**
13.03.2025
- Добавлена возможность отмены текущего действия
```python
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отменяет текущий диалог и очищает данные"""
        # Проверяем, было ли уже обработано это сообщение
        if hasattr(context, '_cancel_processed') and context._cancel_processed:
            return ConversationHandler.END
        context._cancel_processed = True
        user = update.effective_user
        logger.info("User %s canceled the conversation.", user.first_name)
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Все действия отменены. Вы можете начать заново.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
```
24.03.2025
- Реализация механизма уведомлений с разными типами повторений

- ✅ Система хранения параметров в SQLite:
  ```sql
  ALTER TABLE reminders ADD COLUMN repeat_type INTEGER NOT NULL DEFAULT 0
  ALTER TABLE reminders ADD COLUMN repeat_interval INTEGER

06.04.2025
- ✅ Алгоритм пересчета дат:
  ```python
    def calculate_next_run(last_run, repeat_type, interval):
        if repeat_type == RepeatType.DAILY:
            return last_run + timedelta(days=1)
        elif repeat_type == RepeatType.WEEKLY:
            return last_run + timedelta(weeks=1)
        elif repeat_type == RepeatType.CUSTOM:
            return last_run + timedelta(days=interval)
